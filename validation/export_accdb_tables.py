"""Minimal reader for Access (.accdb / Jet4-style) tables -> CSV.

Written because no Access driver or mdbtools is available on this machine.
It reads table-definition pages directly and decodes the rows on each
table's data pages. Supports the column types used by the E-Presso file:
integers, currency, floats, dates, booleans and (compressed) text.

Usage: python validation/export_accdb_tables.py data/Support_EX_B_Sales.accdb validation/exports

This is the FIRST, throw-away prototype reader written while investigating the
file. It is kept as a second, separate implementation: the independent check
uses its CSV output, so the app's own reader (epresso/accdb_reader.py) is
checked against different code. Table pages (41, 96, 826) were found by
listing the table definitions of the original file.
"""
import struct, sys, os, datetime, csv

PAGE = 4096


def u8(b, o): return b[o]
def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


def decode_text(raw):
    if raw[:2] == b'\xff\xfe':  # Jet4 "compressed unicode"
        out, comp, i, data = [], True, 0, raw[2:]
        while i < len(data):
            if data[i] == 0:
                comp = not comp; i += 1; continue
            if comp:
                out.append(chr(data[i])); i += 1
            else:
                out.append(data[i:i+2].decode('utf-16-le', 'replace')); i += 2
        return ''.join(out)
    return raw.decode('utf-16-le', 'replace')


class DB:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        self.npages = len(self.d) // PAGE

    def page(self, n):
        return self.d[n*PAGE:(n+1)*PAGE]

    def tdef_bytes(self, pg):
        p = self.page(pg)
        buf = bytearray(p)
        nxt = u32(p, 4)
        while nxt:
            q = self.page(nxt)
            buf += q[8:]
            nxt = u32(q, 4)
        return bytes(buf)

    def read_tdef(self, pg):
        t = self.tdef_bytes(pg)
        num_rows = u32(t, 16)
        num_var = u16(t, 43)
        num_cols = u16(t, 45)
        num_idx = u32(t, 47)
        num_real_idx = u32(t, 51)
        o = 63 + num_real_idx * 12
        cols = []
        for _ in range(num_cols):
            c = t[o:o+25]
            cols.append(dict(type=c[0], num=u16(c, 5), off_v=u16(c, 7),
                             flags=c[15], off_f=u16(c, 21), length=u16(c, 23)))
            o += 25
        for c in cols:
            ln = u16(t, o); o += 2
            c['name'] = t[o:o+ln].decode('utf-16-le', 'replace'); o += ln
        return dict(page=pg, rows=num_rows, cols=cols, num_cols=num_cols)

    def tables(self):
        out = []
        cont = set()
        for n in range(self.npages):
            p = self.page(n)
            if p[0] == 2 and u32(p, 4):
                cont.add(u32(p, 4))
        for n in range(self.npages):
            p = self.page(n)
            if p[0] == 2 and n not in cont:
                try:
                    out.append(self.read_tdef(n))
                except Exception:
                    pass
        return out

    def rows(self, tdef):
        cols = sorted(tdef['cols'], key=lambda c: c['num'])
        for n in range(self.npages):
            p = self.page(n)
            if p[0] != 1 or u32(p, 4) != tdef['page']:
                continue
            nrows = u16(p, 12)
            offs = [u16(p, 14 + 2*i) for i in range(nrows)]
            for i, raw in enumerate(offs):
                if raw & 0x4000 or raw & 0x8000:   # deleted or overflow pointer
                    continue
                start = raw & 0x1FFF
                end = PAGE if i == 0 else (offs[i-1] & 0x1FFF)
                r = p[start:end]
                yield self.decode_row(r, cols)

    def decode_row(self, r, cols):
        ncols = u16(r, 0)
        mask_sz = (ncols + 7) // 8
        mask = r[len(r)-mask_sz:]
        last = len(r) - 1
        nvar = u16(r, last - mask_sz - 1)
        varoffs = [u16(r, last - mask_sz - 3 - 2*k) for k in range(nvar + 1)]
        rec = {}
        for c in cols:
            present = bool(mask[c['num'] // 8] & (1 << (c['num'] % 8))) if c['num'] // 8 < len(mask) else False
            ty, fixed = c['type'], bool(c['flags'] & 0x01)
            if ty == 1:
                rec[c['name']] = present; continue
            if not present:
                rec[c['name']] = None; continue
            if fixed:
                o = 2 + c['off_f']
                v = r[o:o+c['length']] if c['length'] else r[o:o+8]
            else:
                k = c['off_v']
                if k >= nvar:
                    rec[c['name']] = None; continue
                v = r[varoffs[k]:varoffs[k+1]]
            rec[c['name']] = self.conv(ty, v)
        return rec

    @staticmethod
    def conv(ty, v):
        if ty == 2: return v[0]
        if ty == 3: return struct.unpack('<h', v[:2])[0]
        if ty == 4: return struct.unpack('<i', v[:4])[0]
        if ty == 5: return struct.unpack('<q', v[:8])[0] / 10000
        if ty == 6: return struct.unpack('<f', v[:4])[0]
        if ty == 7: return struct.unpack('<d', v[:8])[0]
        if ty == 8:
            days = struct.unpack('<d', v[:8])[0]
            return (datetime.datetime(1899, 12, 30) + datetime.timedelta(days=days)).strftime('%Y-%m-%d')
        if ty in (0x0A, 0x0C): return decode_text(v)
        return v.hex()


def export(path, out_dir, wanted=('Sales', 'Products', 'Categories')):
    db = DB(path)
    os.makedirs(out_dir, exist_ok=True)
    pages = {41: 'Categories', 96: 'Products', 826: 'Sales'}
    res = {}
    for t in db.tables():
        if t['page'] not in pages: continue
        name = pages[t['page']]
        cols = [c['name'] for c in sorted(t['cols'], key=lambda c: c['num'])]
        rows = list(db.rows(t))
        fn = os.path.join(out_dir, f'{name}.csv')
        with open(fn, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
        res[name] = (t['rows'], len(rows))
    return res


if __name__ == '__main__':
    print(export(sys.argv[1], sys.argv[2]))
