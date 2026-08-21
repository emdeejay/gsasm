"""The opt-in assembly cache (R10, work/_common.py) must never serve a stale object.

A cache that hands back bytes gsasm did not just produce would make the golden
gate report success for code it never assembled — the single worst failure this
repo can have.  These tests are the standing guard for that, and they are
corpus-free: every source here is synthesised in a temp directory, and the cache
is redirected to a temp directory too, so running them never touches work/.cache.

What is asserted, and why each one matters:

  off        with GSASM_CACHE unset the helper is a plain passthrough and
             writes nothing at all (the hard "opt-in" constraint).
  identity   cold and warm return byte-identical OMF.
  mtime      a `touch` with unchanged content is still a HIT — we key on
             CONTENT, because `git checkout` of an older revision restores old
             bytes with a new mtime and `touch` does the reverse.
  content    an edited include recomputes, and returns the NEW bytes.
  shadow     an include planted EARLIER in the search path recomputes, even
             though every file previously read is still byte-identical.  This
             is the case content hashing alone cannot see; it is caught by
             replaying the recorded include probes, misses included.
  defines    a different `defines`/`sysdate` is a different key, not a hit.
  corrupt    a damaged entry is recomputed, never returned.
  interlock  gate.py --update and run_fixtures.py --bless REFUSE to run with
             the cache enabled, and refuse before they write anything.

Run either as:
    python3 -m pytest tests/test_assembly_cache.py
    python3 tests/test_assembly_cache.py
"""
import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'work'))

import _common as C                 # noqa: E402
from gsasm import asm, omf          # noqa: E402

MAIN_SRC = ("t\tPROC\n"
            "\tINCLUDE 'inc.aii'\n"
            "\tlda\t#$12\n"
            "\tENDP\n"
            "\tEND\n")
INC_SRC = "\tdc.b\t$11,$22,$33\n"


class Sandbox:
    """proj/t.asm + lib/inc.aii + an empty shadow/ dir ahead of lib/ on the path."""

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix='r10cache')
        self.cachedir = os.path.join(self.dir, 'cache')
        for sub in ('proj', 'lib', 'shadow'):
            os.makedirs(os.path.join(self.dir, sub))
        self.main = os.path.join(self.dir, 'proj', 't.asm')
        self.inc = os.path.join(self.dir, 'lib', 'inc.aii')
        self.shadow_inc = os.path.join(self.dir, 'shadow', 'inc.aii')
        _write(self.main, MAIN_SRC)
        _write(self.inc, INC_SRC)
        self.incs = [os.path.join(self.dir, 'shadow'),
                     os.path.join(self.dir, 'lib')]
        self._saved_dir = C._CACHE_DIR
        self._saved_env = os.environ.get('GSASM_CACHE')
        self._saved_stats = dict(C.CACHE_STATS)
        C._CACHE_DIR = self.cachedir
        return self

    def __exit__(self, *exc):
        C._CACHE_DIR = self._saved_dir
        C.CACHE_STATS.update(self._saved_stats)
        if self._saved_env is None:
            os.environ.pop('GSASM_CACHE', None)
        else:
            os.environ['GSASM_CACHE'] = self._saved_env
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def run(self, cache_on=True, **kw):
        """Return (sha256 of the emitted OMF, {nonzero cache counter deltas})."""
        before = dict(C.CACHE_STATS)
        if cache_on:
            os.environ['GSASM_CACHE'] = '1'
        else:
            os.environ.pop('GSASM_CACHE', None)
        obj, _errs = C.cached_assemble_emit(self.main, self.incs, **kw)
        delta = {k: C.CACHE_STATS[k] - before[k] for k in C.CACHE_STATS}
        return (hashlib.sha256(obj).hexdigest(),
                {k: v for k, v in delta.items() if v})


def _write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def _direct(sb, **kw):
    """The uncached truth: exactly what the harnesses did before R10."""
    return hashlib.sha256(
        omf.emit(asm.assemble(sb.main, sb.incs, **kw))).hexdigest()


def test_disabled_is_a_passthrough_that_writes_nothing():
    with Sandbox() as sb:
        sha, stats = sb.run(cache_on=False)
        assert sha == _direct(sb), 'uncached helper changed the emitted bytes'
        assert stats == {}, f'counters moved with the cache off: {stats}'
        assert not os.path.exists(sb.cachedir), 'cache dir created while OFF'


def test_cold_and_warm_are_byte_identical():
    with Sandbox() as sb:
        truth = _direct(sb)
        cold, st_cold = sb.run()
        warm, st_warm = sb.run()
        assert st_cold == {'miss': 1}, st_cold
        assert st_warm == {'hit': 1}, st_warm
        assert cold == truth, 'cold run diverged from the uncached truth'
        assert warm == cold, 'warm run diverged from the cold run'


def test_mtime_only_change_is_still_a_hit():
    with Sandbox() as sb:
        truth, _ = sb.run()
        st0 = os.stat(sb.inc)
        os.utime(sb.inc, (st0.st_atime + 9999, st0.st_mtime + 9999))
        sha, stats = sb.run()
        assert stats == {'hit': 1}, f'mtime alone invalidated: {stats}'
        assert sha == truth


def test_edited_include_recomputes_and_returns_the_new_bytes():
    with Sandbox() as sb:
        stale, _ = sb.run()
        _write(sb.inc, "\tdc.b\t$99,$98,$97\n")
        sha, stats = sb.run()
        assert stats == {'stale': 1}, f'edited include not noticed: {stats}'
        assert sha == _direct(sb), 'served bytes are not the new tree'
        assert sha != stale, 'served the pre-edit object'


def test_shadowing_include_recomputes():
    # The case content hashes cannot see: nothing previously read has changed,
    # but a file planted ahead of the winner now wins the search instead.
    with Sandbox() as sb:
        stale, _ = sb.run()
        before = {p: C._sha_file(p) for p in (sb.main, sb.inc)}
        _write(sb.shadow_inc, "\tdc.b\t$77,$76,$75\n")
        assert all(C._sha_file(p) == s for p, s in before.items()), \
            'test bug: the previously-read files must be untouched here'
        sha, stats = sb.run()
        assert stats == {'stale': 1}, f'shadowing include not noticed: {stats}'
        assert sha == _direct(sb), 'served bytes are not the shadowed resolution'
        assert sha != stale, 'served the pre-shadow object'
        os.unlink(sb.shadow_inc)
        back, stats = sb.run()
        assert stats == {'stale': 1}, stats
        assert back == stale, 'removing the shadow did not restore the original'


def test_defines_and_sysdate_are_part_of_the_key():
    with Sandbox() as sb:
        plain, _ = sb.run()
        _, st = sb.run(defines={'R10': 1})
        assert st == {'miss': 1}, f'defines change served a hit: {st}'
        _, st = sb.run(defines={'R10': 1})
        assert st == {'hit': 1}, st
        _, st = sb.run(sysdate='06-May-93')
        assert st == {'miss': 1}, f'sysdate change served a hit: {st}'
        again, st = sb.run()
        assert st == {'hit': 1} and again == plain, \
            'the original entry was disturbed by the variant keys'


def test_damaged_entries_are_recomputed_not_served():
    with Sandbox() as sb:
        truth, _ = sb.run()
        entries = []
        for base, _dirs, files in os.walk(sb.cachedir):
            entries += [os.path.join(base, f) for f in files
                        if f.endswith('.bin')]
        assert len(entries) == 1, entries
        raw = open(entries[0], 'rb').read()
        for label, damaged in (
                ('flipped payload byte', raw[:-1] + bytes([raw[-1] ^ 0xFF])),
                ('truncated', raw[:24]),
                ('empty', b''),
                ('foreign magic', b'NOTOURS!' * 16)):
            with open(entries[0], 'wb') as f:
                f.write(damaged)
            sha, stats = sb.run()
            assert stats == {'miss': 1}, f'{label}: {stats}'
            assert sha == truth, f'{label}: wrong bytes returned'


def test_assert_cache_disabled_fires_on_every_truthy_spelling():
    saved = os.environ.get('GSASM_CACHE')
    try:
        for val in ('1', 'true', 'TRUE', 'yes', 'on'):
            os.environ['GSASM_CACHE'] = val
            raised = None
            try:
                C.assert_cache_disabled('a test')
            except AssertionError as e:
                raised = e
            assert raised is not None, f'interlock did not fire for {val!r}'
            assert 'GSASM_CACHE' in str(raised)
        for val in ('', '0', 'no', 'off'):
            os.environ['GSASM_CACHE'] = val
            C.assert_cache_disabled('a test')      # must NOT raise
        os.environ.pop('GSASM_CACHE', None)
        C.assert_cache_disabled('a test')
    finally:
        if saved is None:
            os.environ.pop('GSASM_CACHE', None)
        else:
            os.environ['GSASM_CACHE'] = saved


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_update_refuses_before_it_can_write_a_baseline():
    gate = _load(os.path.join(REPO, 'work', 'gate.py'), 'r10_gate_probe')
    saved_argv, saved_env = sys.argv, os.environ.get('GSASM_CACHE')
    with tempfile.TemporaryDirectory() as d:
        # Neutered: even a broken interlock cannot reach the real baseline or
        # run a single check.
        gate.BASELINE = os.path.join(d, 'baseline.json')
        gate.run_fixture_suite = lambda: (_ for _ in ()).throw(
            AssertionError('gate ran checks despite the cache interlock'))
        gate.run_check = gate.run_unit_tests = gate.run_fixture_suite
        try:
            sys.argv = ['gate.py', '--update']
            os.environ['GSASM_CACHE'] = '1'
            raised = None
            try:
                gate.main()
            except AssertionError as e:
                raised = e
            assert raised is not None and 'GSASM_CACHE' in str(raised), \
                f'gate.py --update did not refuse the cache: {raised}'
            assert not os.path.exists(gate.BASELINE), 'a baseline was written'
        finally:
            sys.argv = saved_argv
            if saved_env is None:
                os.environ.pop('GSASM_CACHE', None)
            else:
                os.environ['GSASM_CACHE'] = saved_env


def test_bless_refuses_before_it_can_mint_expected_bytes():
    rf = _load(os.path.join(REPO, 'tests', 'run_fixtures.py'), 'r10_bless_probe')
    saved_argv, saved_env = sys.argv, os.environ.get('GSASM_CACHE')
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, 'dummy_fixture'))
        rf.FIXDIR = d                       # never the real tests/fixtures
        rf.bless = lambda fixdir: (_ for _ in ()).throw(
            AssertionError('bless ran despite the cache interlock'))
        rf.run_gate = lambda: (_ for _ in ()).throw(
            AssertionError('gate ran despite the cache interlock'))
        try:
            sys.argv = ['run_fixtures.py', '--bless', '--no-gate']
            os.environ['GSASM_CACHE'] = '1'
            raised = None
            try:
                rf.main()
            except AssertionError as e:
                raised = e
            assert raised is not None and 'GSASM_CACHE' in str(raised), \
                f'--bless did not refuse the cache: {raised}'
        finally:
            sys.argv = saved_argv
            if saved_env is None:
                os.environ.pop('GSASM_CACHE', None)
            else:
                os.environ['GSASM_CACHE'] = saved_env


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for t in tests:
        try:
            t()
            print(f'ok   {t.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
    print(f'{passed}/{len(tests)} passed')
    sys.exit(0 if passed == len(tests) else 1)
