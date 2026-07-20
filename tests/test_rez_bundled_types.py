"""Corpus-free guard for the bundled clean-room type include
(gsasm/rez/include/TypesIIGS.r — docs/REZ_TYPES_PLAN.md).

The include's templates are byte-exact-validated against the golden System
6.0.1 Rez corpus by work/rezbuildcheck.py / work/easymountcheck.py (gate
metrics rez_*).  This test guards what a bare checkout / installed wheel can
check without golden material: the bundled file parses, every corpus-facing
template and constant is present, and a small original resource script
compiles through it to hand-derived bytes (each expectation reproduces a
byte pattern the golden corpus proved: pstring length prefix, rIcon computed
iconSize, rControlTemplate pCount = 3 + optionalCount with partial fill,
rMenu/rControlList zero-long terminators).

Run either as:
    python3 -m pytest tests/test_rez_bundled_types.py
    python3 tests/test_rez_bundled_types.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm.rez import parser, gen                     # noqa: E402

INCDIR = os.path.join(REPO, 'gsasm', 'rez', 'include')

SCRIPT = '''
#include "typesiigs.r"

resource rPString (1) { "Hi" };

resource rIcon (2) {
    0x8000, 2, 4,
    $"AABB",
    $"CCDD"
};

resource rControlTemplate (3) {
    7,
    {1, 2, 3, 4},
    editLineControl {{ 0, 0x7002, 0, 0x1F, 0 }}
};

resource rMenu (4) {
    5, fAllowCache, 6, { 0x100, 0x200 }
};

resource rControlList (5) {
    { 0x10, 0x20 }
};

resource rCDEVFlags (6) {
    wantInit+wantHit, 1, 1, 1, 4,
    {0, 0, 10, 20},
    "Nm", "Au", "V1"
};

resource rToolStartup (10) {
    $C080, { 3, $0302, 34, $0103 }
};

resource rRectList (11) {
    { {1, 2, 3, 4}, {5, 6, 7, 8} }
};

resource rFinderPath (12) {
    {}, "*:X"
};

resource rCString (13) { "Hi" };

resource rText (14) { "Hi" };

resource rBundle (15) {
    1, 15,
    {
        { DontLaunch, {0}, {2}, {3} },
        FileType|NetworkAccess,
        MatchFileType {{ $0f }},
        empty{}, empty{}, empty{}, empty{}, empty{},
        matchNetworkAccess {{ 7, 4 }},
        empty{}, empty{}, empty{}, empty{}, empty{}
    }
};

resource rControlTemplate (16) {
    3,
    {35, 14, 44, 294},
    thermometerControl {{ 1, $1000, 0, 0, 100 }}
};
'''


def _build():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'guard.r')
        with open(src, 'w') as fh:
            fh.write(SCRIPT)
        stmts = parser.parse(src, include_dirs=[INCDIR],
                             predefined={'RezIIGS': 1})
        return {e.rid: e.data for e in gen.generate(stmts)
                if e.kind == 'resource'}


def test_bundled_types_compile():
    data = _build()
    # pstring: length byte + chars
    assert data[1] == b'\x02Hi'
    # rIcon: type, computed iconSize (=len(image)), height, width, image, mask
    assert data[2] == (b'\x00\x80' b'\x02\x00' b'\x02\x00' b'\x04\x00'
                       b'\xaa\xbb' b'\xcc\xdd')
    # rControlTemplate editLine: pCount = 3 + 5 supplied params (partial
    # fill: the 6th optional field is omitted), key procRef 0x83000000
    d = data[3]
    assert d[0:2] == b'\x08\x00', f'pCount {d[0:2].hex()}'
    assert d[2:6] == b'\x07\x00\x00\x00'
    assert d[14:18] == b'\x00\x00\x00\x83'
    assert d[26:28] == b'\x1f\x00'                       # max length
    # rMenu: version 0, id, flags, titleRef, item refs, zero terminator
    assert data[4] == (b'\x00\x00' b'\x05\x00' b'\x08\x00'
                       b'\x06\x00\x00\x00'
                       b'\x00\x01\x00\x00' b'\x00\x02\x00\x00'
                       b'\x00\x00\x00\x00')
    # rControlList: refs + zero terminator
    assert data[5] == (b'\x10\x00\x00\x00' b'\x20\x00\x00\x00'
                       b'\x00\x00\x00\x00')
    # rCDEVFlags: flags word, 4 bytes, rect, then FIXED-CAPACITY pstrings —
    # pstring[N] stores N+1 bytes (golden General CDEV: 16/33/9 fields)
    assert data[6] == (b'\x08\x02' b'\x01\x01\x01\x04'
                       b'\x00\x00\x00\x00\x0a\x00\x14\x00'
                       + b'\x02Nm' + b'\x00' * 13
                       + b'\x02Au' + b'\x00' * 30
                       + b'\x02V1' + b'\x00' * 6)
    # rToolStartup: flags 0, video mode, resFileID 0, dPageHandle 0,
    # count, (tool, minVersion) pairs — all little-endian (golden Finder
    # instance layout)
    assert data[10] == (b'\x00\x00' b'\x80\xc0' b'\x00\x00'
                        b'\x00\x00\x00\x00' b'\x02\x00'
                        b'\x03\x00\x02\x03' b'\x22\x00\x03\x01')
    # rRectList: count word + 8-byte rects
    assert data[11] == (b'\x02\x00'
                        b'\x01\x00\x02\x00\x03\x00\x04\x00'
                        b'\x05\x00\x06\x00\x07\x00\x08\x00')
    # rFinderPath: version 0, byte offset of the pathname (6), empty
    # array, then a word-length GS/OS pathname
    assert data[12] == b'\x00\x00' b'\x06\x00\x00\x00' b'\x03\x00' b'*:X'
    # rCString adds the trailing NUL; rText does not
    assert data[13] == b'Hi\x00'
    assert data[14] == b'Hi'
    # rBundle: 18-byte header; the OneDoc reproduces the golden 70-byte
    # shape (size word self-inclusive, matchFlags offset 32, launch count
    # 4, 8-byte refs, matchFlags long, tagged sections with zero-word
    # empties)
    assert data[15] == (
        b'\x00\x00' b'\x10\x00'                       # version, count offset
        b'\x01\x00\x00\x00' b'\x0f\x00\x00\x00'       # finder icon, bundle ID
        b'\x00\x00\x00\x00' b'\x01\x00'               # reserved, doc count
        b'\x46\x00' b'\x20\x00' b'\x04\x00'           # size, matchOff, nElems
        b'\x00\x00'                                   # DontLaunch
        b'\x00\x00\x00\x00\x00\x00\x00\x00'           # path ref
        b'\x02\x00\x00\x00\x00\x00\x00\x00'           # big icon ref
        b'\x03\x00\x00\x00\x00\x00\x00\x00'           # small icon ref
        b'\x41\x00\x00\x00'                           # FileType|NetworkAccess
        b'\x01\x00' b'\x0f\x00'                       # sec 1: file type $0F
        + b'\x00\x00' * 5                             # secs 2-6 empty
        + b'\x07\x00'                                 # sec 7 tag
        b'\x07\x00\x00\x00' b'\x04\x00\x00\x00'       # mask, value
        + b'\x00\x00' * 5)                            # secs 8-12 empty
    # thermometerControl: procRef $87FF0002, value + scale params
    assert data[16] == (b'\x08\x00' b'\x03\x00\x00\x00'
                        b'\x23\x00\x0e\x00\x2c\x00\x26\x01'
                        b'\x02\x00\xff\x87'
                        b'\x01\x00' b'\x00\x10' b'\x00\x00\x00\x00'
                        b'\x00\x00' b'\x64\x00')


if __name__ == '__main__':
    test_bundled_types_compile()
    print('ok')
