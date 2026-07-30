"""Corpus-free test for the Rez `data` statement (packet R1).

`data <typeID> (<id>[, "<name>"][, <attrs>...]) { $"hex..." }` is a
template-free resource: the brace body is a run of adjacent hex-/string
literals whose bytes become the resource's data VERBATIM, with no type
template consulted. It is what MPW `DeRezIIgs` emits and what `data`
compiles straight back to; the System 6.0.1 System-Sounds and TeachText
docs build their whole resource fork from `data` statements alone
(work/rezdatacheck.py proves those byte-exact).

Everything here is ORIGINAL input (no Apple material) exercising, in
isolation, the three library behaviors this packet added:

  1. the parser emits a `DataStmt` whose `body` is the literal run;
  2. `gen.generate` turns it into a `kind == 'data'` entry whose `data` is
     the verbatim byte concatenation (hex as-is, string escapes decoded),
     and resolves the `purgeable3` attribute keyword to 0x0300;
  3. `gen.to_emit_tuples` lays the rResName-type ($8014) resource LAST in
     the data region even when it is the FIRST statement in source order
     (the System-Sounds layout quirk), which `emit.emit_fork` then honors.

Run either as:
    python3 -m pytest tests/test_rez_data_stmt.py
    python3 tests/test_rez_data_stmt.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm.rez import parser, gen, emit  # noqa: E402

RESNAME_TYPE = 0x8014


def _parse(text):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'in.r')
        with open(p, 'w', encoding='latin-1') as fh:
            fh.write(text)
        return parser.parse(p)


def test_parser_emits_datastmt_with_verbatim_body():
    stmts = _parse('data 0x7001 (1) { $"AD00 7C02" $"1A00" };\n')
    assert len(stmts) == 1
    s = stmts[0]
    assert isinstance(s, parser.DataStmt)
    assert s.typeid == 0x7001
    assert isinstance(s.id, parser.Num) and s.id.value == 1
    assert s.name is None and s.attrs == []
    # body is the parsed literal run; each segment a HexLit.
    joined = b''.join(seg.value for seg in s.body)
    assert joined == bytes.fromhex('AD007C021A00')


def test_gen_data_entry_is_verbatim_bytes():
    stmts = _parse('data 0x9000 (5) { $"0102" $"030405" };\n')
    entries = gen.generate(stmts)
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == 'data'
    assert e.rtype == 0x9000 and e.rid == 5
    assert e.data == bytes([1, 2, 3, 4, 5])


def test_data_string_segment_escapes_decoded():
    # A string segment in a data body is decoded the same way every other
    # Rez string is (\0xHH -> one byte); hex segments stay verbatim.
    stmts = _parse('data 0x9000 (1) { "AB\\0x00" $"FF" };\n')
    e = gen.generate(stmts)[0]
    assert e.data == b'AB\x00\xff'


def test_purgeable3_attribute_word():
    stmts = _parse('data 0x8012 (1, purgeable3) { $"00" };\n')
    e = gen.generate(stmts)[0]
    assert e.attr == 0x0300


def test_data_body_may_be_empty():
    stmts = _parse('data 0x9000 (1) { };\n')
    e = gen.generate(stmts)[0]
    assert e.data == b''


def test_resname_type_ordered_last_in_data_region():
    # $8014 declared FIRST in source, a non-name resource SECOND: the
    # data-region order must place $8014 LAST (System-Sounds layout).
    src = ('data 0x8014 (0x18024) { $"AAAA" };\n'
           'data 0x8024 (0xF) { $"BBBBBB" };\n')
    stmts = _parse(src)
    entries = gen.generate(stmts)
    assert [e.rtype for e in entries] == [0x8014, 0x8024]  # source order kept
    tuples = gen.to_emit_tuples(entries)
    # to_emit_tuples reorders: $8024 first, $8014 (rResName type) last.
    assert [t[0] for t in tuples] == [0x8024, 0x8014]
    assert [t[3] for t in tuples] == [b'\xbb\xbb\xbb', b'\xaa\xaa']


def test_full_fork_places_resname_data_last():
    src = ('data 0x8014 (0x18024) { $"AAAA" };\n'
           'data 0x8024 (0xF) { $"BBBBBB" };\n')
    tuples = gen.to_emit_tuples(gen.generate(_parse(src)))
    fork = emit.emit_fork(tuples, {'name': 'Snd'})
    # The two data blobs sit contiguously at the end, $8024's first.
    assert fork.endswith(b'\xbb\xbb\xbb' + b'\xaa\xaa')
    # And the index (sorted by type) still resolves both resources.
    assert fork.count(b'\xbb\xbb\xbb') == 1
    assert fork.count(b'\xaa\xaa') >= 1


def test_data_attr_keyword_and_numeric_combine():
    # A bare numeric attribute OR's in alongside a keyword (generic path).
    stmts = _parse('data 0x9000 (1, purgeable3, 0x0040) { $"00" };\n')
    e = gen.generate(stmts)[0]
    assert e.attr == (0x0300 | 0x0040)


_TESTS = [(n, f) for n, f in sorted(globals().items())
          if n.startswith('test_') and callable(f)]


if __name__ == '__main__':
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f'FAIL {name}: {exc}')
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'ERROR {name}: {exc!r}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
