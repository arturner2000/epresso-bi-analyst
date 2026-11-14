"""Pure-Python reader for Microsoft Access (.accdb / .mdb Jet4+) tables.

Why this exists: the E-Presso Sales, Products and Categories tables come in an
Access database. Streamlit Community Cloud runs Linux, where there is no Access
driver, and we did not want to depend on a system package (mdbtools). This
module reads the file format directly and returns each table as a pandas
DataFrame, so the app can accept the original .accdb file (or a modified copy)
with no conversion step.

Scope (deliberately small): it reads table-definition pages and data pages,
and decodes the column types found in ordinary tables: yes/no, byte, integer,
long integer, currency, single, double, date/time and short text. Memo/long
text and attachment columns are returned as None. It never writes to the file.

Format reference: the mdbtools project's documentation of the Jet4 page layout.
"""
from __future__ import annotations

import datetime as _dt
import struct

import pandas as pd

PAGE_SIZE = 4096

# Access column type codes
T_BOOL, T_BYTE, T_INT, T_LONG, T_MONEY, T_FLOAT, T_DOUBLE, T_DATETIME = 1, 2, 3, 4, 5, 6, 7, 8
T_TEXT, T_MEMO = 0x0A, 0x0C


class AccessFormatError(ValueError):
    """Raised when the bytes do not look like a readable Access database."""


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _decode_text(raw: bytes) -> str:
    """Jet4 text is UTF-16-LE, optionally 'compressed' (marker FF FE)."""
    if raw[:2] == b"\xff\xfe":
        out, compressed, i, data = [], True, 0, raw[2:]
        while i < len(data):
            if data[i] == 0:  # a zero byte toggles compressed/uncompressed mode
                compressed = not compressed
                i += 1
                continue
            if compressed:
                out.append(chr(data[i]))
                i += 1
            else:
                out.append(data[i:i + 2].decode("utf-16-le", "replace"))
                i += 2
        return "".join(out)
    return raw.decode("utf-16-le", "replace")


class AccessDB:
    def __init__(self, data: bytes):
        if len(data) < PAGE_SIZE * 3 or data[4:19] not in (b"Standard ACE DB", b"Standard Jet DB"):
            raise AccessFormatError("This file is not a recognised Access database (.accdb/.mdb).")
        if data[4:19] == b"Standard Jet DB" and data[0x14] == 0:
            raise AccessFormatError("Access 97 (Jet3) files are not supported; save the database as .accdb.")
        self.d = data
        self.n_pages = len(data) // PAGE_SIZE
        self._tdefs = None

    # ------------------------------------------------------------------ pages
    def _page(self, n: int) -> bytes:
        return self.d[n * PAGE_SIZE:(n + 1) * PAGE_SIZE]

    def _tdef_bytes(self, pg: int) -> bytes:
        p = self._page(pg)
        buf, nxt, seen = bytearray(p), _u32(p, 4), {pg}
        while nxt and nxt not in seen and nxt < self.n_pages:
            seen.add(nxt)
            q = self._page(nxt)
            buf += q[8:]
            nxt = _u32(q, 4)
        return bytes(buf)

    def _read_tdef(self, pg: int) -> dict:
        t = self._tdef_bytes(pg)
        num_rows = _u32(t, 16)
        num_cols = _u16(t, 45)
        num_real_idx = _u32(t, 51)
        o = 63 + num_real_idx * 12
        cols = []
        for _ in range(num_cols):
            c = t[o:o + 25]
            cols.append({"type": c[0], "num": _u16(c, 5), "var_index": _u16(c, 7),
                         "flags": c[15], "fixed_offset": _u16(c, 21), "length": _u16(c, 23)})
            o += 25
        for c in cols:
            ln = _u16(t, o)
            o += 2
            c["name"] = t[o:o + ln].decode("utf-16-le", "replace")
            o += ln
        cols.sort(key=lambda c: c["num"])
        return {"page": pg, "declared_rows": num_rows, "columns": cols}

    def table_definitions(self) -> list[dict]:
        if self._tdefs is None:
            continuation = set()
            for n in range(self.n_pages):
                p = self._page(n)
                if p[0] == 2 and _u32(p, 4):
                    continuation.add(_u32(p, 4))
            tdefs = []
            for n in range(1, self.n_pages):
                p = self._page(n)
                if p[0] == 2 and n not in continuation:
                    try:
                        tdefs.append(self._read_tdef(n))
                    except (struct.error, IndexError, UnicodeDecodeError):
                        continue
            names = self._table_names(tdefs)
            for t in tdefs:
                t["name"] = names.get(t["page"])
            self._tdefs = tdefs
        return self._tdefs

    def _table_names(self, tdefs) -> dict:
        """Map tdef page -> table name using the MSysObjects system table (page 2)."""
        sys_t = next((t for t in tdefs if t["page"] == 2), None)
        if not sys_t:
            return {}
        names = {}
        for r in self._rows(sys_t):
            if r.get("Type") == 1 and r.get("Id") is not None and r.get("Name"):
                names[r["Id"] & 0x00FFFFFF] = r["Name"]
        return names

    # ------------------------------------------------------------------- rows
    def _row_slices(self, tdef_page: int):
        """Yield (page_no, row_no, raw_bytes) for every live row of a table."""
        pages = [n for n in range(self.n_pages)
                 if self.d[n * PAGE_SIZE] == 1 and _u32(self.d, n * PAGE_SIZE + 4) == tdef_page]
        # Rows that were moved to an overflow location are reached through a
        # pointer row; remember their targets so they are not read twice.
        pointers, targets = [], set()
        for n in pages:
            p = self._page(n)
            offs = [_u16(p, 14 + 2 * i) for i in range(_u16(p, 12))]
            for i, raw in enumerate(offs):
                if raw & 0x8000 and not raw & 0x4000:
                    start = raw & 0x1FFF
                    ptr = p[start:start + 4]
                    tgt = (_u32(ptr + b"\x00", 1) & 0xFFFFFF, ptr[0])
                    pointers.append((n, i, tgt))
                    targets.add(tgt)
        for n in pages:
            p = self._page(n)
            offs = [_u16(p, 14 + 2 * i) for i in range(_u16(p, 12))]
            for i, raw in enumerate(offs):
                if raw & 0x4000 or raw & 0x8000 or (n, i) in targets:
                    continue
                yield n, i, self._slice(p, offs, i)
        for _, _, (tp, tr) in pointers:
            for _hop in range(4):  # follow (rare) chains of overflow pointers
                p = self._page(tp)
                offs = [_u16(p, 14 + 2 * k) for k in range(_u16(p, 12))]
                if tr >= len(offs):
                    break
                raw = offs[tr]
                if raw & 0x8000:
                    start = raw & 0x1FFF
                    ptr = p[start:start + 4]
                    tp, tr = _u32(ptr + b"\x00", 1) & 0xFFFFFF, ptr[0]
                    continue
                yield tp, tr, self._slice(p, offs, tr)
                break

    @staticmethod
    def _slice(p, offs, i):
        start = offs[i] & 0x1FFF
        end = PAGE_SIZE
        for k in range(i - 1, -1, -1):  # row i ends where the previous row starts
            end = offs[k] & 0x1FFF
            break
        return p[start:end]

    def _rows(self, tdef):
        for _, _, r in self._row_slices(tdef["page"]):
            rec = self._decode_row(r, tdef["columns"])
            if rec is not None:
                yield rec

    def _decode_row(self, r: bytes, cols):
        if len(r) < 4:
            return None
        n_cols = _u16(r, 0)
        mask_sz = (n_cols + 7) // 8
        mask = r[len(r) - mask_sz:]
        last = len(r) - 1
        n_var = _u16(r, last - mask_sz - 1)
        var_offs = [_u16(r, last - mask_sz - 3 - 2 * k) for k in range(n_var + 1)]
        rec = {}
        for c in cols:
            num = c["num"]
            present = num // 8 < len(mask) and bool(mask[num // 8] & (1 << (num % 8)))
            if c["type"] == T_BOOL:
                rec[c["name"]] = present
                continue
            if not present:
                rec[c["name"]] = None
                continue
            if c["flags"] & 0x01:  # fixed-length column
                o = 2 + c["fixed_offset"]
                v = r[o:o + (c["length"] or 8)]
            else:
                k = c["var_index"]
                if k >= n_var:
                    rec[c["name"]] = None
                    continue
                v = r[var_offs[k]:var_offs[k + 1]]
            rec[c["name"]] = self._convert(c["type"], v)
        return rec

    @staticmethod
    def _convert(ty, v):
        try:
            if ty == T_BYTE:
                return v[0]
            if ty == T_INT:
                return struct.unpack("<h", v[:2])[0]
            if ty == T_LONG:
                return struct.unpack("<i", v[:4])[0]
            if ty == T_MONEY:
                return struct.unpack("<q", v[:8])[0] / 10000
            if ty == T_FLOAT:
                return struct.unpack("<f", v[:4])[0]
            if ty == T_DOUBLE:
                return struct.unpack("<d", v[:8])[0]
            if ty == T_DATETIME:
                days = struct.unpack("<d", v[:8])[0]
                return _dt.datetime(1899, 12, 30) + _dt.timedelta(days=days)
            if ty == T_TEXT:
                return _decode_text(v)
        except (struct.error, IndexError, OverflowError):
            return None
        return None  # memo / OLE / attachment etc. are not needed here

    # ------------------------------------------------------------ public API
    def user_tables(self) -> list[dict]:
        """Table definitions excluding Access system tables."""
        return [t for t in self.table_definitions()
                if t.get("name") and not t["name"].startswith(("MSys", "f_", "~"))]

    def read_table(self, tdef: dict) -> pd.DataFrame:
        names = [c["name"] for c in tdef["columns"]]
        return pd.DataFrame(list(self._rows(tdef)), columns=names)

    def tables(self) -> dict[str, pd.DataFrame]:
        return {t["name"]: self.read_table(t) for t in self.user_tables()}


def read_accdb(data: bytes) -> dict[str, pd.DataFrame]:
    """Return {table_name: DataFrame} for every user table in the database."""
    return AccessDB(data).tables()
