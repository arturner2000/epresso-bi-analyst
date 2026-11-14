"""Create a COPY of the Access database with one Revenue value changed (for the $1,000 test).

Access is not available on macOS, so this script edits the copy directly: it
finds the row with the given Sales ID and overwrites its 8-byte Revenue value.
Nothing else in the file changes. The original file is never modified.

Usage:
    python validation/make_modified_accdb.py data/Support_EX_B_Sales.accdb \
        modified/Support_EX_B_Sales.accdb S1120290112 1000
"""
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from epresso.accdb_reader import PAGE_SIZE, T_DOUBLE, AccessDB  # noqa: E402


def modify(src, dst, sales_id, delta):
    data = bytearray(Path(src).read_bytes())
    db = AccessDB(bytes(data))
    sales = next(t for t in db.user_tables() if t["name"] == "Sales")
    rev = next(c for c in sales["columns"] if c["name"] == "Revenue")
    assert rev["type"] == T_DOUBLE, "Revenue is expected to be a Double column"
    for page_no, row_no, raw in db._row_slices(sales["page"]):
        rec = db._decode_row(raw, sales["columns"])
        if rec.get("Sales ID") == sales_id:
            page = db._page(page_no)
            row_start = struct.unpack_from("<H", page, 14 + 2 * row_no)[0] & 0x1FFF
            if rev["flags"] & 0x01:  # fixed-length storage
                in_row = 2 + rev["fixed_offset"]
            else:  # variable-length storage: look up the offset table at the end of the row
                n_cols = struct.unpack_from("<H", raw, 0)[0]
                mask_sz = (n_cols + 7) // 8
                last = len(raw) - 1
                in_row = struct.unpack_from("<H", raw, last - mask_sz - 3 - 2 * rev["var_index"])[0]
            pos = page_no * PAGE_SIZE + row_start + in_row
            old = struct.unpack_from("<d", data, pos)[0]
            struct.pack_into("<d", data, pos, old + delta)
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_bytes(bytes(data))
            return rec, old, old + delta
    raise SystemExit(f"Sales ID {sales_id} not found")


if __name__ == "__main__":
    src, dst, sid, delta = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
    if Path(src).resolve() == Path(dst).resolve():
        raise SystemExit("Refusing to overwrite the original file; choose a different output path.")
    rec, old, new = modify(src, dst, sid, delta)
    print(f"Row: {rec}")
    print(f"Revenue {old:,.2f} -> {new:,.2f} written to {dst}")
