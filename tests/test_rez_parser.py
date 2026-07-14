"""Hand-authored unit tests for gsasm/rez/parser.py (work packet R4).

These are original snippets (NOT derived from Apple sources) each pinning one
grammar production discovered while parsing the real corpus
(work/rezparsecheck.py runs the corpus check itself; that harness lives
under work/ because the corpus it reads is gitignored Apple material — this
file only ever needs small strings we write ourselves, following the style
of tests/test_rez_lexer.py).

Run either as:
    python3 -m pytest tests/test_rez_parser.py
    python3 tests/test_rez_parser.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm.rez import parser  # noqa: E402


def _parse(data, name='t.r', include_dirs=None):
    """Write `data` (str, encoded latin-1, or bytes) to a temp file named
    `name` and return `parser.parse(...)` over it."""
    if isinstance(data, str):
        data = data.encode('latin-1')
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, name)
        with open(path, 'wb') as f:
            f.write(data)
        return parser.parse(path, include_dirs=include_dirs)


# --------------------------------------------------------------------------
# `type` declaration: labels, a sized hex-string field, a `= const` default,
# and NUMBER-as-typename (a macro-expanded `#define` typeid, exactly how
# `rMyCursor`/`rIcon`/... arrive from the corpus's TypesIIGS.r table).
# --------------------------------------------------------------------------
def test_type_decl_with_labels_and_sized_string_and_number_typeid():
    src = (
        b'#define rMyCursor $8027\r'
        b'type rMyCursor {\r'
        b'\theight:\r'
        b'\t\thex integer;\r'
        b'\twidth:\r'
        b'\t\thex integer;\r'
        b'\thex string[2*$$Word(height)*$$Word(width)];\r'
        b'\tlongint = 0;\r'
        b'};\r'
    )
    stmts = _parse(src)
    assert len(stmts) == 1
    decl = stmts[0]
    assert isinstance(decl, parser.TypeDecl)
    assert decl.typeid == 0x8027   # NUMBER, not the IDENT 'rMyCursor'
    assert decl.id_range is None
    # height: / width: labels, then the sized hex-string field, then a
    # plain longint default.
    assert isinstance(decl.fields[0], parser.Label)
    assert decl.fields[0].name == 'height'
    assert isinstance(decl.fields[1], parser.TypedField)
    assert decl.fields[1].basetype == 'integer'
    assert decl.fields[1].modifiers == ['hex']
    assert isinstance(decl.fields[2], parser.Label)
    assert decl.fields[2].name == 'width'
    sized = decl.fields[4]
    assert isinstance(sized, parser.TypedField)
    assert sized.basetype == 'string'
    assert sized.modifiers == ['hex']
    assert isinstance(sized.size, parser.BinOp)  # 2*$$Word(h)*$$Word(w)
    last = decl.fields[5]
    assert isinstance(last, parser.TypedField)
    assert last.basetype == 'longint'
    assert isinstance(last.default, parser.Num) and last.default.value == 0


# --------------------------------------------------------------------------
# `switch { case Name: key ... ; ... }` template, with a named-value list
# (some entries implicit, matching rTERuler's justification field) and a
# nested `array` inside one case.
# --------------------------------------------------------------------------
def test_type_decl_with_switch_and_array_and_named_values():
    src = (
        b'type 1 {\r'
        b'\tinteger leftJust, centerJust, fullJust, rightJust = -1;\r'
        b'\tswitch {\r'
        b'\tcase NoTabRuler:\r'
        b'\t\tkey integer = 0;\r'
        b'\tcase AbsoluteTabRuler:\r'
        b'\t\tkey integer = 2;\r'
        b'\t\twide array TabStops {\r'
        b'\t\t\tinteger = 0;\r'
        b'\t\t\tinteger;\r'
        b'\t\t};\r'
        b'\t\thex integer = -1;\r'
        b'\t};\r'
        b'};\r'
    )
    stmts = _parse(src)
    decl = stmts[0]
    assert decl.typeid == 1
    named = decl.fields[0]
    assert isinstance(named, parser.TypedField)
    names = [nv.name for nv in named.named_values]
    assert names == ['leftJust', 'centerJust', 'fullJust', 'rightJust']
    assert named.named_values[0].value is None       # implicit
    # explicit `-1`: unary minus reassembled into a UnaryOp around Num(1)
    # (the lexer never folds sign into NUMBER; see its module docstring)
    rj_value = named.named_values[3].value
    assert isinstance(rj_value, parser.UnaryOp)
    assert rj_value.op == '-' and rj_value.operand.value == 1

    sw = decl.fields[1]
    assert isinstance(sw, parser.SwitchField)
    assert [c.name for c in sw.cases] == ['NoTabRuler', 'AbsoluteTabRuler']
    case1 = sw.cases[1]
    assert isinstance(case1.fields[0], parser.TypedField) and case1.fields[0].key
    arr = case1.fields[1]
    assert isinstance(arr, parser.ArrayField)
    assert arr.wide is True
    assert arr.name == 'TabStops'
    assert arr.bound is None
    assert len(arr.fields) == 2
    # trailing `hex integer = -1;` after the array, back in the case body
    assert isinstance(case1.fields[2], parser.TypedField)
    assert case1.fields[2].modifiers == ['hex']


# --------------------------------------------------------------------------
# A bare `name { fields };` group (generalizes the corpus's one-off
# `ReverseBytes { ... };` in rVersion, without hard-coding that name).
# --------------------------------------------------------------------------
def test_bare_named_group_field():
    src = (
        b'type 2 {\r'
        b'\tReverseBytes {\r'
        b'\t\thex byte;\r'
        b'\t\thex bitstring[4];\r'
        b'\t};\r'
        b'\tinteger;\r'
        b'};\r'
    )
    stmts = _parse(src)
    decl = stmts[0]
    grp = decl.fields[0]
    assert isinstance(grp, parser.GroupField)
    assert grp.keyword == 'ReverseBytes'
    assert len(grp.fields) == 2
    assert grp.fields[1].basetype == 'bitstring'
    assert isinstance(grp.fields[1].size, parser.Num) and grp.fields[1].size.value == 4


# --------------------------------------------------------------------------
# `fill`/`optional` fields, and a parenthesized type id-range (grammar-
# supported per the design doc even though the corpus never exercises it).
# --------------------------------------------------------------------------
def test_fill_and_optional_and_id_range():
    src = (
        b'type 3 (1, 10) {\r'
        b'\tfill long[3];\r'
        b'\toptional Fields {\r'
        b'\t\tinteger;\r'
        b'\t};\r'
        b'};\r'
    )
    stmts = _parse(src)
    decl = stmts[0]
    assert decl.id_range is not None
    first, second = decl.id_range
    assert first.value == 1 and second.value == 10
    fill = decl.fields[0]
    assert isinstance(fill, parser.FillField)
    assert fill.unit == 'long'
    assert fill.count.value == 3
    opt = decl.fields[1]
    assert isinstance(opt, parser.OptionalField)
    assert opt.name == 'Fields'
    assert len(opt.fields) == 1


# --------------------------------------------------------------------------
# `resource` statement: numeric+named+attr header, nested-array values,
# a symbolic-name value, string concatenation, and a hex-string run.
# --------------------------------------------------------------------------
def test_resource_with_header_and_nested_values():
    src = (
        b'resource 1(1, "Stop", locked, fixed, $8000) {\r'
        b'\t{ 6,0,1,release,$00 },\r'
        b'\tverUS,\r'
        b'\t"System Software"\r'
        b'\t"Copyright Apple Computer, Inc. 1983-93",\r'
        b'\t$"0011FF"\r'
        b'\t$"22"\r'
        b'};\r'
    )
    stmts = _parse(src)
    res = stmts[0]
    assert isinstance(res, parser.ResourceStmt)
    assert res.typeid == 1
    assert isinstance(res.id, parser.Num) and res.id.value == 1
    assert res.name == b'Stop'
    assert len(res.attrs) == 3
    assert isinstance(res.attrs[0], parser.Name) and res.attrs[0].name == 'locked'
    assert isinstance(res.attrs[2], parser.Num) and res.attrs[2].value == 0x8000

    group = res.values[0]
    assert isinstance(group, parser.GroupValue)
    assert len(group.values) == 5
    assert isinstance(group.values[3], parser.Name) and group.values[3].name == 'release'

    assert isinstance(res.values[1], parser.Name) and res.values[1].name == 'verUS'

    strlit = res.values[2]
    assert isinstance(strlit, parser.StrLit)
    assert strlit.value == (b'System Software'
                             b'Copyright Apple Computer, Inc. 1983-93')

    hexlit = res.values[3]
    assert isinstance(hexlit, parser.HexLit)
    assert hexlit.value == bytes.fromhex('0011FF22')


# --------------------------------------------------------------------------
# A `switch`-case selector value (double-brace form: `Name {{ ... }}`,
# matching rControlTemplate's `statTextControl {{ ... }}`), plus the
# comma/semicolon-interchangeable trailing separator quirk (see the
# module docstring's "Value-list separators" note).
# --------------------------------------------------------------------------
def test_case_value_and_trailing_semicolon_before_close_brace():
    src = (
        b'resource 4 (1) {\r'
        b'\t$00000001,\r'
        b'\tstatTextControl {{\r'
        b'\t\t$0003,\r'
        b'\t\t$1002\r'
        b'\t}};\r'
        b'};\r'
    )
    stmts = _parse(src)
    res = stmts[0]
    case = res.values[1]
    assert isinstance(case, parser.CaseValue)
    assert case.name == 'statTextControl'
    assert len(case.values) == 1
    inner = case.values[0]
    assert isinstance(inner, parser.GroupValue)
    assert [v.value for v in inner.values] == [0x0003, 0x1002]
    # the trailing `;` right before the outer `}` (rather than nothing, or
    # a comma) must not break parsing — see parse_value_list.
    assert len(res.values) == 2


def test_trailing_comma_before_close_brace_in_nested_array():
    src = (
        b'resource 3 (1) {\r'
        b'\t{\r'
        b'\tCTLTMP_1,\r'
        b'\tCTLTMP_2,\r'
        b'\t};\r'
        b'};\r'
    )
    stmts = _parse(src)
    res = stmts[0]
    grp = res.values[0]
    assert isinstance(grp, parser.GroupValue)
    assert [v.name for v in grp.values] == ['CTLTMP_1', 'CTLTMP_2']


# --------------------------------------------------------------------------
# `read` statement.
# --------------------------------------------------------------------------
def test_read_statement():
    src = b'read 23 (0x07FF0001,Convert,locked)  "IconButton.Load";\r'
    stmts = _parse(src)
    assert len(stmts) == 1
    rd = stmts[0]
    assert isinstance(rd, parser.ReadStmt)
    assert rd.typeid == 23
    assert rd.id.value == 0x07FF0001
    assert rd.name is None
    assert [a.name for a in rd.attrs] == ['Convert', 'locked']
    assert rd.filename == b'IconButton.Load'


# --------------------------------------------------------------------------
# `$$Func(...)` expressions, including the `name[$$ArrayIndex(name)]`
# subscript-reference form (rBundle's
# `end[$$ArrayIndex(OneDocs)]-startOneDoc[$$ArrayIndex(OneDocs)]`).
# --------------------------------------------------------------------------
def test_dollar_dollar_expressions_and_subscript_reference():
    src = (
        b'type 5 {\r'
        b'\tinteger = (end[$$ArrayIndex(OneDocs)]'
        b'-startOneDoc[$$ArrayIndex(OneDocs)])/8;\r'
        b'};\r'
    )
    stmts = _parse(src)
    default = stmts[0].fields[0].default
    assert isinstance(default, parser.BinOp) and default.op == '/'
    assert default.right.value == 8
    numerator = default.left
    assert isinstance(numerator, parser.BinOp) and numerator.op == '-'
    left = numerator.left
    assert isinstance(left, parser.Subscript)
    assert left.name == 'end'
    assert isinstance(left.index, parser.Call)
    assert left.index.func == '$$ArrayIndex'
    assert left.index.args[0].name == 'OneDocs'
    assert isinstance(numerator.right, parser.Subscript)
    assert numerator.right.name == 'startOneDoc'


# --------------------------------------------------------------------------
# Multiple adjacent STRING literals concatenate (design-doc note: string
# concatenation is the parser's job, not the lexer's).
# --------------------------------------------------------------------------
def test_string_concatenation_in_resource_value():
    src = b'resource 6 (1) { "ab" "cd" "ef" };\r'
    stmts = _parse(src)
    assert stmts[0].values[0].value == b'abcdef'


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
