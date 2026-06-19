#!/usr/bin/env python3
"""Minimal read-only HFS (standard) extractor. Handles extents-overflow."""
import struct, sys, os

class HFS:
    def __init__(self, path):
        self.img = open(path, 'rb').read()
        b = self.img
        assert b[1024:1026] == b'BD', "not HFS standard"
        self.alBlkSiz = struct.unpack('>I', b[1024+20:1024+24])[0]
        self.alBlSt   = struct.unpack('>H', b[1024+28:1024+30])[0]
        self.catSize  = struct.unpack('>I', b[1024+146:1024+150])[0]
        self.catExt   = self._exts(1024+150)
        self.xtExt    = self._exts(1024+134)
        self.NS = 512
        self.dirs = {2: (0, '')}
        self.files = {}
        self._build()

    def _exts(self, o):
        e = []
        for i in range(3):
            s = struct.unpack('>H', self.img[o:o+2])[0]
            c = struct.unpack('>H', self.img[o+2:o+4])[0]
            o += 4
            if c:
                e.append((s, c))
        return e

    def _ablk(self, n):
        return self.alBlSt*512 + n*self.alBlkSiz

    def _fork(self, exts):
        return b''.join(self.img[self._ablk(s):self._ablk(s)+c*self.alBlkSiz] for s, c in exts)

    def _recs(self, nd):
        NS = self.NS
        nr = struct.unpack('>H', nd[10:12])[0]
        offs = [struct.unpack('>H', nd[NS-2*(i+1):NS-2*i])[0] for i in range(nr+1)]
        return [nd[offs[i]:offs[i+1]] for i in range(nr)]

    def _leaves(self, buf):
        NS = self.NS
        total = len(buf)//NS
        first = struct.unpack('>I', buf[24:28])[0]
        out = []
        n = first
        seen = set()
        while n and n not in seen and n < total:
            seen.add(n)
            nd = buf[n*NS:(n+1)*NS]
            if nd[8] != 0xFF:
                break
            out.extend(self._recs(nd))
            n = struct.unpack('>I', nd[0:4])[0]
        return out

    def _build(self):
        # extents-overflow extras for catalog (cnid 4, data fork)
        extra = {}
        for r in self._leaves(self._fork(self.xtExt)):
            if not r or r[0] < 7:
                continue
            fork = r[1]; fnum = struct.unpack('>I', r[2:6])[0]; fabn = struct.unpack('>H', r[6:8])[0]
            ex = []
            o = 8
            for i in range(3):
                s = struct.unpack('>H', r[o:o+2])[0]; c = struct.unpack('>H', r[o+2:o+4])[0]; o += 4
                if c: ex.append((s, c))
            extra.setdefault((fork, fnum), []).append((fabn, ex))
        catexts = list(self.catExt)
        for fabn, ex in sorted(extra.get((0, 4), [])):
            catexts += ex
        cat = self._fork(catexts)[:self.catSize]
        for r in self._leaves(cat):
            if not r or r[0] == 0:
                continue
            parID = struct.unpack('>I', r[2:6])[0]; nlen = r[6]
            name = r[7:7+nlen].decode('mac_roman', 'replace')
            doff = 1+r[0]
            if doff % 2: doff += 1
            ctype = r[doff]
            if ctype == 1:
                dirID = struct.unpack('>I', r[doff+6:doff+10])[0]
                self.dirs[dirID] = (parID, name)
            elif ctype == 2:
                b = doff
                ft = r[b+4:b+8]; lg = struct.unpack('>I', r[b+26:b+30])[0]
                cnid = struct.unpack('>I', r[b+20:b+24])[0]
                eo = b+74; ext = []
                for i in range(3):
                    s = struct.unpack('>H', r[eo:eo+2])[0]; c = struct.unpack('>H', r[eo+2:eo+4])[0]; eo += 4
                    if c: ext.append((s, c))
                for fabn, ex in sorted(extra.get((0, cnid), [])):
                    ext += ex
                self.files[(parID, name)] = (lg, ext, ft)

    def path(self, parID):
        parts = []; cur = parID
        while cur in self.dirs and cur not in (0, 2):
            p, nm = self.dirs[cur]; parts.append(nm); cur = p
        return '/'.join(reversed(parts))

    def data(self, parID, name):
        lg, ext, ft = self.files[(parID, name)]
        return self._fork(ext)[:lg]


if __name__ == '__main__':
    vol = HFS(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else 'list'
    rows = sorted(vol.files.keys(), key=lambda k: (vol.path(k[0]), k[1]))
    if cmd == 'list':
        for parID, name in rows:
            lg, ext, ft = vol.files[(parID, name)]
            print(f"{vol.path(parID)+'/'+name:75s}{lg:9d}  {ft.decode('mac_roman','replace')}")
        print(f"# total {len(vol.files)} files, {len(vol.dirs)} dirs", file=sys.stderr)
    elif cmd == 'count':
        print(f"{len(vol.files)} files {len(vol.dirs)} dirs")
    elif cmd == 'extract':
        pat = sys.argv[3].lower(); outdir = sys.argv[4]; n = 0
        for parID, name in rows:
            full = (vol.path(parID)+'/'+name).lower()
            if pat in full:
                d = os.path.join(outdir, vol.path(parID)); os.makedirs(d, exist_ok=True)
                open(os.path.join(d, name.replace('/', '_')), 'wb').write(vol.data(parID, name)); n += 1
        print(f"extracted {n} files matching {pat!r}")
