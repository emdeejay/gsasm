#!/usr/bin/env python3
"""toolsetup_probe.py — diagnostic for the Tool.Setup disk file.

Reproduces the System.Setup/Tool.Setup ExpressLoad build (multi-object,
segment-name-filtered, 2 -lseg groups `main`+`patches`) from clean-room source
and diffs it against the shipping binary.  RESULT (see docs/design/FINAL_RUN.md):
both segments' CODE lengths match exactly (1078 + 16402); the only residual is
relocation-record ENCODING — gsasm SUPER-izes all relocs, golden keeps 31
standalone cINTERSEG (main) + 11 standalone cRELOC (patches).  That is the
case-B ExpressLoad converter wall (docs/design/expressload.md), so Tool.Setup
is code-exact but NOT byte-exact and is deliberately left unwired.

Needs a2til (set A2TIL_PATH or place as a sibling of gsasm).  Run from repo root.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.environ.get('A2TIL_PATH',
                                  os.path.expanduser('~/src/a2til')))
from gsasm import asm, omf
from gsasm.expressload import expressload
import diskbuilders.expressload_files as ef

TB=ef._TB; incs=ef._TOOL_INCS

def asm_obj(path):
    a=asm.assemble(path, [path.rsplit('/',1)[0]]+incs)
    return omf.emit(a)

def filter_segname(obj, names):
    """Keep only segments whose SEGNAME (uppercased, stripped) is in names, in the LISTED order."""
    segs={}
    off=0; order=[]
    while off<len(obj):
        h=omf.parse_header(obj[off:]); bc=h['BYTECNT']
        if not bc: break
        nm=h['SEGNAME'].rstrip(b'\x00 ').upper()
        segs.setdefault(nm, obj[off:off+bc])
        off+=bc
    out=b''
    for n in names:
        u=n.upper().encode() if isinstance(n,str) else n.upper()
        if u in segs: out+=segs[u]
        else: print('  MISS seg', n)
    return out

# main group = setup.asm (all segments)
main_combo = asm_obj(f'{TB}/Patch/Setup/setup.asm')

# patches group, in makefile order
loc = filter_segname(asm_obj(f'{TB}/Patch/Patch3/Locator.pch'),
  ['GODDAMMIT','GETMSGHANDLE','MCGETFIRSTMESSAGE','MCGETNEXTMESSAGE','ACCEPTREQUESTS','SENDREQUEST','ADDTBNOTIFYPROC','ADDTBREQUESTHANDLER','UNKNOWNDISKREQPROC'])
sst = asm_obj(f'{TB}/tl/startstop.asm')  # ALL
ldg = filter_segname(asm_obj(f'{TB}/tl/loading.asm'),
  ['LOADONETOOL','LOADTOOLS','LOADTHISTOOL','TLGETMEM','MAKEIDNUM','GETSPECIALFLAG','UNLOADONETOOL','UNLOADTOOLS','DUMMYTABLE','REPORTIFMISSING'])
tl_ = filter_segname(asm_obj(f'{TB}/tl/tl.asm'), ['TLMEMROUTINES','DUMMYTABLE'])
com = asm_obj(f'{TB}/common/common.asm')  # ALL
msc = filter_segname(asm_obj(f'{TB}/Patch/Patch3/Misc.tools.pch'),
  ['UNPACKBYTES','CONVSECONDS','SYSBEEP2','VERSIONSTRING','WAITUNTIL','STRINGTOTEXT','SHOWBOOTINFO','SCANDEVICES','TOBRAMSETUPPATCH','ALERTMESSAGE','DOSYSPREFS'])
cda_o=asm_obj(f'{TB}/Desk/CDAMenu.asm')
cda = filter_segname(cda_o,
  ['DAHANDLER','DOCDAMENU','SORTCDAS','CHOOSECDA','INITSTUFF','GOTRETURN','MONKEYIN','EVNTKEYIN','UPDATECDAMENU','PRINTDALIST','WRITEDANAME','SETUPTAB','OPENDA','DEREF','DISPLAYDATA','COUT','MYCOUT','MYWRITECSTRING','MYWRITELINE',
   'SETSCREENLOC','DEREFCDAY','PANELACTIVE','GETCDANUM','SEARCHCDALETTER'])
nda_o=asm_obj(f'{TB}/Desk/NDACalls.asm')
nda = filter_segname(nda_o,
  ['SYSTEMEVENT','CALLCDAMENU','CHECKNDASTUFF','STARTNDACALL','DESKUTILS','AREWETOP','ENDNDACALL','FINDTHISWINDOW','SENDACTION','SENDOPEN','SENDINIT','SENDCLOSE','FUTZRESIDS','FRONTTOAX',
   'SYSTEMCLICK','SYSTEMEDIT','SYSTEMTASK','CLOSENDABYWINPTR','CLOSEALLNDAS2','DIEHORRIBLY','FIXAPPLEMENU2','REMOVENDA','GETDESKACCINFO','CALLDESKACC','GETDESKGLOBAL','DOCLOSESTUFF','EXECUTERUNITEM'])

patches_combo = loc+sst+ldg+tl_+com+msc+cda+nda

mine = expressload([(main_combo,None),(patches_combo,None)],
  opts={'multiseg':True,'segnames':[b'main',b'patches'],'segkinds':[0x3000,0x0000]})

from a2til.prodos import Volume
buf=bytearray(open("ref/GSOS_6/System601_disks/System 6.0.1/Disk 2 of 7 System Disk.2mg",'rb').read())
g=Volume(buf).read_file('/System.Disk/System/System.Setup/Tool.Setup')
print('mine',len(mine),'golden',len(g),'delta',len(g)-len(mine))
n=min(len(mine),len(g)); m=sum(1 for i in range(n) if mine[i]==g[i])
print(f'match {m}/{n} ({100*m//n}%)')
fd=next((i for i in range(n) if mine[i]!=g[i]),None)
print('first diff',hex(fd) if fd is not None else None)
if fd is not None:
    print('mine',mine[max(0,fd-6):fd+16].hex()); print('gold',g[max(0,fd-6):fd+16].hex())
