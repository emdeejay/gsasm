"""gsmake (MPW IIgs makefile runner) — gsasm/mpwmake.py.

Corpus-free: a synthetic MacRoman/CR makefile with ƒ-rules, ∂-continuations,
{var} expansion, comments and Mac :-paths drives the real asmiigs/linkiigs
dispatch end to end (including the objcache bridge that lets a
-lseg:Dynamic link consume the .obj names the makefile writes), plus unit
tests for the parser pieces and the stale-link re-assembly path.

Run either as:
    python3 -m pytest tests/test_mpwmake.py
    python3 tests/test_mpwmake.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import mpwmake as M, omf                  # noqa: E402

F = 'ƒ'    # ƒ
C = '∂'    # ∂

_MAIN_SRC = """\
Main\tPROC
\tEXPORT\tMain
\tIMPORT\tFarRtn
\tjsl\tFarRtn
\trts
\tENDP
\tEND
"""

_PREP_SRC = """\
FarRtn\tPROC
\tEXPORT\tFarRtn
\tlda\t#$0001
\trtl
\tENDP
\tEND
"""

# The LW makefile's shape, with variables, continuations, mixed-case file
# spellings, a comment, and a redirect — everything the dialect throws at us.
_MAKEFILE = f"""\
DRV = outdrv

### build the driver
{{DRV}}\t{F}\tmain.aii.obj prep.aii.obj
\tlinkiigs -l >{{DRV}}.map {C}
\t\t-lseg MAIN main.aii.obj {C}
\t\t-lseg:Dynamic PREP prep.aii.obj {C}
\t\t-o {{DRV}} -t $BB -at $0001

Main.AII.obj\t{F}\tmain.aii
\tasmiigs Main.aii   # case differs from the file on purpose

prep.aii.obj\t{F}\tprep.aii
\tasmiigs prep.aii
"""


def _mkdir():
    d = tempfile.mkdtemp(prefix='gsmake-test-')
    with open(os.path.join(d, 'main.aii'), 'w') as fh:
        fh.write(_MAIN_SRC)
    with open(os.path.join(d, 'prep.aii'), 'w') as fh:
        fh.write(_PREP_SRC)
    # MacRoman + CR line endings, like the originals.
    with open(os.path.join(d, 'makefile'), 'wb') as fh:
        fh.write(_MAKEFILE.replace('\n', '\r').encode('mac_roman'))
    return d


def test_mac_to_posix():
    f = M.mac_to_posix
    assert f(':obj:') == 'obj'
    assert f(':a:b') == 'a/b'
    assert f('::') == '..'
    assert f('::foo:bar') == '../foo/bar'
    assert f(':a::') == 'a/..'
    assert f('plain.obj') == 'plain.obj'
    assert f('dir/kept.obj') == 'dir/kept.obj'


def test_parser():
    rules, assigns = M.parse_makefile(_MAKEFILE)
    assert assigns == {'drv': 'outdrv'}
    assert [r.targets[0] for r in rules] == ['{DRV}', 'Main.AII.obj',
                                             'prep.aii.obj']
    link = rules[0]
    assert link.deps == ['main.aii.obj', 'prep.aii.obj']
    # ∂-joined into ONE logical recipe line, comment stripped elsewhere.
    assert len(link.recipe) == 1
    assert '-lseg:Dynamic PREP' in link.recipe[0]
    assert '#' not in rules[1].recipe[0]


def test_expand_undefined_names_the_variable():
    try:
        M.expand('{NoSuch}', {})
    except SystemExit as e:
        assert 'NoSuch' in str(e)
    else:
        raise AssertionError('expected MakeError')


def test_end_to_end_dynamic_link():
    d = _mkdir()
    M.main(['-C', d, '--always', '-q'])
    load = open(os.path.join(d, 'outdrv'), 'rb').read()
    names = [s['name'] for s in omf.iter_segments(load, records=False)]
    assert names == ['~ExpressLoad', 'MAIN', '~JumpTable', 'PREP'], names
    # The mixed-case recipe wrote Main.aii.obj; the link consumed it via
    # the case-folded objcache.
    assert any(f.lower() == 'main.aii.obj' for f in os.listdir(d))


def test_stale_link_fresh_objs_reassembles():
    d = _mkdir()
    M.main(['-C', d, '--always', '-q'])
    os.utime(os.path.join(d, 'outdrv'), (1, 1))     # only the link is stale
    M.main(['-C', d, '-q'])                          # fresh Maker: empty cache
    load = open(os.path.join(d, 'outdrv'), 'rb').read()
    names = [s['name'] for s in omf.iter_segments(load, records=False)]
    assert '~JumpTable' in names, names


def test_up_to_date_skips():
    d = _mkdir()
    M.main(['-C', d, '--always', '-q'])
    before = os.path.getmtime(os.path.join(d, 'outdrv'))
    M.main(['-C', d, '-q'])
    assert os.path.getmtime(os.path.join(d, 'outdrv')) == before


def test_conditionals():
    d = tempfile.mkdtemp(prefix='gsmake-test-')
    mk = ("dup = 1\n"
          f"t\t{F}\t\n"
          "\tIf {dup}\n"
          "\techo yes-dup > took.txt\n"
          "\tEnd\n"
          "\tIf {missing}\n"            # undefined -> empty -> false
          "\techo never > bad.txt\n"
          "\tElse\n"
          "\techo else-arm > good.txt\n"
          "\tEnd\n"
          "\tIf {dup} == 2\n"
          "\techo never2 > bad2.txt\n"
          "\tEnd\n")
    with open(os.path.join(d, 'makefile'), 'wb') as fh:
        fh.write(mk.replace('\n', '\r').encode('mac_roman'))
    M.main(['-C', d, '--always', '-q', 't'])
    files = set(os.listdir(d))
    assert 'took.txt' in files and 'good.txt' in files, files
    assert 'bad.txt' not in files and 'bad2.txt' not in files, files


def test_suffix_rule_and_default():
    d = tempfile.mkdtemp(prefix='gsmake-test-')
    with open(os.path.join(d, 'sub.aii'), 'w') as fh:
        fh.write(_PREP_SRC)
    mk = (f"sub.aii.obj\t{F}{F}\tsub.aii\n"      # explicit, always-build
          "\tasmiigs {Targ.src}.aii -o {Targ}\n"
          .replace('{Targ.src}', 'sub').replace('{Targ}', '{Targ}'))
    # Exercise the suffix form too: .obj ƒ .aii with a second source.
    with open(os.path.join(d, 'other.aii'), 'w') as fh:
        fh.write(_PREP_SRC)
    mk += (f"\n.obj\t{F}\t.aii\n"
           "\tasmiigs {Default}.aii -o {Default}.obj\n")
    with open(os.path.join(d, 'makefile'), 'wb') as fh:
        fh.write(mk.replace('\n', '\r').encode('mac_roman'))
    M.main(['-C', d, '--always', '-q', 'sub.aii.obj', 'other.obj'])
    files = {f.lower() for f in os.listdir(d)}
    assert 'sub.aii.obj' in files, files        # concrete rule + {Default}
    assert 'other.obj' in files, files          # suffix rule synthesis


if __name__ == '__main__':
    for nm, fn in sorted(globals().items()):
        if nm.startswith('test_') and callable(fn):
            fn()
            print(f'{nm}: PASS')
