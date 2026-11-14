"""Load, validate and model the E-Presso data.

The app accepts the three original course files in their original formats:

    Support_EX_B_Sales.accdb   -> tables Sales, Products, Categories
    Support_EX_B_Stores.csv    -> stores (tab-separated)
    Support_EX_B_Survey.xlsx   -> sheet "Survey Results"

Any table may also be supplied as its own .csv / .txt / .xlsx file (for example
a Sales table exported from Access). Files are recognised by their COLUMNS,
not their names, and any table that is not uploaded falls back to the bundled
original data. Every loaded table records where it came from.

Data model (verified grains, see GRAIN below):

    Sales  (fact, one row per store x product x month)
      Store ID    -> Stores.ID           many-to-one
      Product ID  -> Products.Product ID many-to-one
      Category ID -> Categories.Category ID many-to-one
      StoreYear   -> Survey.Survey ID    many-to-one (used only after the fact
                                         table is aggregated to store-year)
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .accdb_reader import AccessFormatError, read_accdb

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_FILES = ["Support_EX_B_Sales.accdb", "Support_EX_B_Stores.csv", "Support_EX_B_Survey.xlsx"]

REQUIRED = {
    "Sales": ["Sales ID", "Date", "Store ID", "StoreYear", "Category ID", "Product ID", "Revenue"],
    "Stores": ["ID", "City", "State", "StoreType", "Market", "Location"],
    "Survey": ["Survey ID", "Store ID", "Year", "Satisfaction", "Interest"],
    "Products": ["Product ID", "Product"],
    "Categories": ["Category ID", "Category"],
}

GRAIN = [
    {"Table": "Sales", "Source": "Support_EX_B_Sales.accdb / Sales",
     "One row =": "monthly revenue for one store (or the website) and one product",
     "Key column(s)": "Sales ID (unique); natural key Store ID + Product ID + Date",
     "Contains revenue?": "Yes - Revenue"},
    {"Table": "Stores", "Source": "Support_EX_B_Stores.csv",
     "One row =": "one location: 20 brick-and-mortar stores + the website (SH00)",
     "Key column(s)": "ID", "Contains revenue?": "No"},
    {"Table": "Products", "Source": "Support_EX_B_Sales.accdb / Products",
     "One row =": "one product", "Key column(s)": "Product ID", "Contains revenue?": "No"},
    {"Table": "Categories", "Source": "Support_EX_B_Sales.accdb / Categories",
     "One row =": "one product category", "Key column(s)": "Category ID", "Contains revenue?": "No"},
    {"Table": "Survey", "Source": "Support_EX_B_Survey.xlsx / Survey Results",
     "One row =": "one yearly market survey result for one store",
     "Key column(s)": "Survey ID (= Store ID + '_' + 2-digit year, matches Sales.StoreYear)",
     "Contains revenue?": "No"},
]


class DataError(ValueError):
    """A problem with the supplied files that the user can fix (shown as a plain message)."""


@dataclass
class Model:
    sales: pd.DataFrame          # enriched fact table (one row per Sales row, never more)
    stores: pd.DataFrame
    products: pd.DataFrame
    categories: pd.DataFrame
    survey: pd.DataFrame
    sources: dict                # table -> description of where it came from
    raw_counts: dict             # table -> rows as loaded
    merge_log: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fingerprint: str = ""


# --------------------------------------------------------------------- reading
def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _find_header(raw: pd.DataFrame, must_have: str) -> pd.DataFrame:
    """Excel sheets in this course have title rows above the header; find the real header row."""
    for i in range(min(len(raw), 15)):
        vals = [str(v).strip() for v in raw.iloc[i].tolist()]
        if must_have in vals:
            out = raw.iloc[i + 1:].copy()
            out.columns = vals
            out = out.loc[:, [c for c in out.columns if c and c != "nan"]]
            return out.dropna(how="all").reset_index(drop=True)
    return _clean_cols(raw)


def _classify(df: pd.DataFrame) -> str | None:
    cols = set(df.columns)
    for name, req in REQUIRED.items():
        if set(req) <= cols:
            return name
    return None


def _missing_cols_message(df: pd.DataFrame, fname: str) -> str:
    cols = set(df.columns)
    best = max(REQUIRED, key=lambda k: len(set(REQUIRED[k]) & cols))
    missing = [c for c in REQUIRED[best] if c not in cols]
    return (f"'{fname}' looks like the {best} table but is missing required column(s): "
            f"{', '.join(missing)}. Columns found: {', '.join(map(str, df.columns))}.")


def read_any(name: str, data: bytes) -> dict[str, pd.DataFrame]:
    """Read one uploaded file into {table_kind: DataFrame}. Raises DataError with a plain message."""
    low = name.lower()
    found: dict[str, pd.DataFrame] = {}
    candidates: list[pd.DataFrame] = []
    try:
        if low.endswith((".accdb", ".mdb")):
            for tname, df in read_accdb(data).items():
                candidates.append(_clean_cols(df))
        elif low.endswith((".xlsx", ".xlsm")):
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None)
            for sname, raw in sheets.items():
                for key in ("Survey ID", "Sales ID", "Product ID", "Category ID", "ID"):
                    df = _find_header(raw, key)
                    if _classify(df):
                        candidates.append(df)
                        break
                else:
                    if sname.strip().lower() == "survey results":
                        candidates.append(_find_header(raw, "Survey ID"))
        elif low.endswith((".csv", ".txt", ".tsv")):
            text = data.decode("utf-8-sig", errors="replace")
            sep = "\t" if text.split("\n", 1)[0].count("\t") >= text.split("\n", 1)[0].count(",") else ","
            candidates.append(_clean_cols(pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=True)))
        else:
            raise DataError(f"'{name}': unsupported file type. Use .accdb, .csv, .txt or .xlsx.")
    except AccessFormatError as e:
        raise DataError(f"'{name}': {e}") from e
    except DataError:
        raise
    except Exception as e:  # unreadable / corrupt file
        raise DataError(f"'{name}' could not be read ({type(e).__name__}: {e}).") from e

    for df in candidates:
        kind = _classify(df)
        if kind:
            found[kind] = df
    if not found:
        msgs = [_missing_cols_message(df, name) for df in candidates if len(df.columns)]
        raise DataError(msgs[0] if msgs else f"'{name}' does not contain any E-Presso table.")
    return found


# ------------------------------------------------------------------ type rules
def _to_num(s: pd.Series) -> pd.Series:
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        s = s.astype("string").str.replace(r"[$,\s]", "", regex=True).replace("", pd.NA)
    return pd.to_numeric(s, errors="coerce").astype("float64")


def _to_str(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip()
    return out.mask(out.isin(["", "nan", "None", "<NA>"]))


def _prepare(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if kind == "Sales":
        for c in ["Sales ID", "Store ID", "StoreYear", "Category ID", "Product ID"]:
            df[c] = _to_str(df[c])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Revenue"] = _to_num(df["Revenue"])
    elif kind == "Stores":
        for c in df.columns:
            df[c] = _to_str(df[c])
    elif kind == "Survey":
        for c in ["Survey ID", "Store ID", "Year"]:
            df[c] = _to_str(df[c])
        df["Satisfaction"] = _to_num(df["Satisfaction"])
        df["Interest"] = _to_num(df["Interest"])
        df["Survey Year"] = pd.to_numeric(df["Year"].str.extract(r"(\d{4})")[0], errors="coerce").astype("Int64")
    else:
        for c in df.columns:
            df[c] = _to_str(df[c])
    return df.reset_index(drop=True)


# ----------------------------------------------------------------- merge check
def check_merge(left: pd.DataFrame, merged: pd.DataFrame, label: str, value_col: str = "Revenue") -> dict:
    """Rows and revenue before/after a merge. A change means the join duplicated or dropped rows."""
    rec = {
        "Merge": label,
        "Rows before": int(len(left)), "Rows after": int(len(merged)),
        "Revenue sum before": float(left[value_col].sum()) if value_col in left else np.nan,
        "Revenue sum after": float(merged[value_col].sum()) if value_col in merged else np.nan,
    }
    same = rec["Rows before"] == rec["Rows after"] and np.isclose(rec["Revenue sum before"], rec["Revenue sum after"])
    rec["OK"] = bool(same)
    return rec


def _dedupe_dim(df: pd.DataFrame, key: str, kind: str, warnings: list) -> pd.DataFrame:
    dups = df[key].duplicated(keep="first") & df[key].notna()
    if dups.any():
        warnings.append(f"{kind}: {int(dups.sum())} duplicate {key} value(s) "
                        f"({', '.join(df.loc[dups, key].astype(str).unique()[:5])}); the first occurrence is used "
                        f"so the join cannot duplicate revenue.")
    return df[~dups & df[key].notna()]


def _store_label(store_type, city, sid) -> pd.Series:
    """'City (ID)' for stores, 'Website (ID)' for the website, 'Unknown store (ID)' if not in Stores."""
    sid = sid.astype("string").fillna("?")
    is_web = store_type.astype("string").fillna("").eq("Website")
    unknown = store_type.isna()
    lab = city.astype("string").fillna("Unknown city") + " (" + sid + ")"
    lab = lab.mask(is_web, "Website (" + sid + ")").mask(unknown, "Unknown store (" + sid + ")")
    return lab.astype("string")


# ------------------------------------------------------------------ build model
def build_model(tables: dict[str, pd.DataFrame], sources: dict[str, str]) -> Model:
    missing = [k for k in REQUIRED if k not in tables]
    if missing:
        raise DataError(f"Missing table(s): {', '.join(missing)}.")
    t = {k: _prepare(k, v) for k, v in tables.items()}
    raw_counts = {k: int(len(v)) for k, v in t.items()}
    warnings: list[str] = []

    stores = _dedupe_dim(t["Stores"], "ID", "Stores", warnings)
    products = _dedupe_dim(t["Products"], "Product ID", "Products", warnings)
    categories = _dedupe_dim(t["Categories"], "Category ID", "Categories", warnings)
    survey = t["Survey"]

    sales = t["Sales"].copy()
    log = []
    s_cols = ["ID", "City", "State", "StoreType", "Market", "Location"]
    m1 = sales.merge(stores[s_cols].rename(columns={"ID": "Store ID"}), on="Store ID", how="left", validate="m:1")
    log.append(check_merge(sales, m1, "Sales -> Stores on Store ID = ID (m:1, left)"))
    m2 = m1.merge(products[["Product ID", "Product"]], on="Product ID", how="left", validate="m:1")
    log.append(check_merge(m1, m2, "+ Products on Product ID (m:1, left)"))
    m3 = m2.merge(categories[["Category ID", "Category"]], on="Category ID", how="left", validate="m:1")
    log.append(check_merge(m2, m3, "+ Categories on Category ID (m:1, left)"))
    if not all(r["OK"] for r in log):
        raise DataError("A join changed the number of rows or the revenue total. See the merge log.")

    df = m3
    df["Year"] = df["Date"].dt.year.astype("Int64")
    df["Month"] = df["Date"].dt.month.astype("Int64")
    df["Channel"] = df["StoreType"].fillna("Unknown store")
    df["Store"] = _store_label(df["StoreType"], df["City"], df["Store ID"])
    df["Category"] = df["Category"].fillna("Unknown category (" + df["Category ID"].fillna("blank") + ")")
    df["Product Label"] = (df["Product"].fillna("Unknown product") + " (" + df["Product ID"].fillna("?") + ")")

    stores = stores.copy()
    stores["Store"] = _store_label(stores["StoreType"], stores["City"], stores["ID"])

    fp = f"{len(df)}|{df['Revenue'].sum():.2f}"
    return Model(sales=df, stores=stores, products=products, categories=categories, survey=survey,
                 sources=sources, raw_counts=raw_counts, merge_log=log, warnings=warnings, fingerprint=fp)


def load(uploads: list[tuple[str, bytes]] | None = None) -> Model:
    """Load uploaded files (name, bytes); any table not uploaded comes from the bundled originals."""
    tables, sources = {}, {}
    for fname in DEFAULT_FILES:
        p = DATA_DIR / fname
        if p.exists():
            for kind, df in read_any(fname, p.read_bytes()).items():
                tables[kind], sources[kind] = df, f"Original course file ({fname})"
    for fname, data in uploads or []:
        for kind, df in read_any(fname, data).items():
            tables[kind], sources[kind] = df, f"UPLOADED: {fname}"
    return build_model(tables, sources)
