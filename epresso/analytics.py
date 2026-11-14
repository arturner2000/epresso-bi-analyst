"""Analytical functions shared by the dashboard AND the assistant.

Every public function follows the same "tool contract" so that a number never
appears without its definition and scope:

    {
      "tool":       function name,
      "value":      the calculated result (numbers / tables as lists of dicts),
      "definition": how the value was calculated,
      "scope":      the filters that were applied (explicit parameters only),
      "rows_used":  number of Sales rows that went into the calculation,
      "caveats":    limitations a reader must know,
    }

On bad input (e.g. a store that does not exist) the function returns the same
structure with an "error" key instead of guessing.

Functions take explicit parameters (year, channel, store, category). They never
read hidden dashboard state, and they never modify the data passed to them.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

REVENUE_NOT_PROFIT = "Revenue is sales revenue, not profit: the data contains no costs, expenses or margins."
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

CHANNEL_ALIASES = {
    "website": "Website", "web": "Website", "online": "Website", "internet": "Website", "e-commerce": "Website",
    "brick & mortar": "Brick & Mortar", "brick and mortar": "Brick & Mortar", "brick-and-mortar": "Brick & Mortar",
    "stores": "Brick & Mortar", "physical": "Brick & Mortar", "retail": "Brick & Mortar", "store": "Brick & Mortar",
}


# ------------------------------------------------------------------- helpers
def _r(x, nd=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def _as_list(v) -> list | None:
    if v is None or v == "" or v == "All" or (isinstance(v, (list, tuple, set)) and len(v) == 0):
        return None
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [v]


def _result(tool, value, definition, scope, rows_used, caveats=None, error=None) -> dict:
    out = {"tool": tool, "value": value, "definition": definition, "scope": scope,
           "rows_used": int(rows_used), "caveats": list(dict.fromkeys(caveats or []))}
    if error:
        out["error"] = error
    return out


def allowed_values(df: pd.DataFrame) -> dict:
    """Values that exist in the CURRENT data. Filter lists and assistant parameters come from here."""
    years = sorted(int(y) for y in df["Year"].dropna().unique())
    return {
        "year": years,
        "channel": sorted(df["Channel"].dropna().unique().tolist()),
        "store": sorted(df["Store"].dropna().unique().tolist()),
        "category": sorted(df["Category"].dropna().unique().tolist()),
    }


def resolve_channel(df, value):
    if value is None:
        return None, None
    key = str(value).strip().lower()
    chans = set(df["Channel"].dropna().unique())
    for c in chans:
        if c.lower() == key:
            return c, None
    c = CHANNEL_ALIASES.get(key)
    if c in chans:
        return c, None
    return None, f"Unknown channel '{value}'. Valid channels: {', '.join(sorted(chans))}."


def resolve_store(df, value):
    """Accept a store label 'Chicago (SH11)', a Store ID 'SH11', or a unique city name 'Chicago'."""
    if value is None:
        return None, None
    v = str(value).strip()
    labels = df[["Store", "Store ID", "City", "Channel"]].drop_duplicates()
    for col in ("Store", "Store ID"):
        hit = labels[labels[col].str.lower() == v.lower()]
        if len(hit) == 1:
            return hit["Store"].iloc[0], None
    if v.lower() in ("website", "web", "online"):
        hit = labels[labels["Channel"] == "Website"]
        if len(hit) == 1:
            return hit["Store"].iloc[0], None
    hit = labels[labels["City"].fillna("").str.lower() == v.lower()]
    if len(hit) == 1:
        return hit["Store"].iloc[0], None
    if len(hit) > 1:
        return None, (f"'{v}' matches more than one store: {', '.join(hit['Store'])}. "
                      f"Please name the store by its ID.")
    return None, f"Unknown store '{v}'. Valid stores: {', '.join(sorted(labels['Store']))}."


def resolve_category(df, value):
    if value is None:
        return None, None
    cats = sorted(df["Category"].dropna().unique())
    v = str(value).strip().lower()
    for c in cats:
        if c.lower() == v or c.lower().rstrip("s") == v.rstrip("s"):
            return c, None
    return None, f"Unknown category '{value}'. Valid categories: {', '.join(cats)}."


def apply_filters(df: pd.DataFrame, year=None, channel=None, store=None, category=None):
    """Return (filtered_df, scope_dict, error). Parameters may be single values or lists."""
    scope, out = {}, df
    years = _as_list(year)
    if years:
        try:
            years = [int(y) for y in years]
        except (TypeError, ValueError):
            return None, None, f"Year must be a number such as 2027 (got {year})."
        valid = set(allowed_values(df)["year"])
        bad = [y for y in years if y not in valid]
        if bad:
            return None, None, f"Year(s) {bad} not in the data. Available years: {sorted(valid)}."
        out = out[out["Year"].isin(years)]
    scope["year"] = years if years else "All"

    resolved = {}
    for name, val, fn in (("channel", channel, resolve_channel), ("store", store, resolve_store),
                          ("category", category, resolve_category)):
        vals = _as_list(val)
        if not vals:
            scope[name] = "All"
            continue
        res = []
        for v in vals:
            r, err = fn(df, v)
            if err:
                return None, None, err
            res.append(r)
        resolved[name] = res
        scope[name] = res if len(res) > 1 else res[0]
    if "channel" in resolved:
        out = out[out["Channel"].isin(resolved["channel"])]
    if "store" in resolved:
        out = out[out["Store"].isin(resolved["store"])]
    if "category" in resolved:
        out = out[out["Category"].isin(resolved["category"])]
    return out, scope, None


def _missing_revenue_caveat(d: pd.DataFrame) -> list:
    n = int(d["Revenue"].isna().sum())
    return [f"{n} row(s) in scope have a blank or non-numeric Revenue and were excluded from sums."] if n else []


def _undated_caveat(d: pd.DataFrame) -> list:
    n = int(d["Date"].isna().sum())
    return [f"{n} row(s) in scope have no valid Date and are excluded from year/month breakdowns."] if n else []


def _pct(new, old):
    if old is None or new is None or old == 0 or pd.isna(old):
        return None
    return (new - old) / old * 100


# ---------------------------------------------------------------- functions
def get_revenue_summary(df, year=None, channel=None, store=None, category=None) -> dict:
    """Total revenue for any combination of filters."""
    tool = "get_revenue_summary"
    d, scope, err = apply_filters(df, year, channel, store, category)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    total = d["Revenue"].sum()
    value = {"total_revenue": _r(total), "sales_rows": int(len(d)),
             "stores_in_scope": int(d["Store"].nunique()),
             "years_in_scope": sorted(int(y) for y in d["Year"].dropna().unique())}
    cav = [REVENUE_NOT_PROFIT] + _missing_revenue_caveat(d)
    if len(d) == 0:
        cav.append("No sales rows match this scope.")
    return _result(tool, value, "Sum of Sales.Revenue over the rows in scope.", scope, len(d), cav)


def get_revenue_by_channel(df, year=None, store=None, category=None) -> dict:
    """Website vs brick-and-mortar revenue and share of the in-scope total."""
    tool = "get_revenue_by_channel"
    d, scope, err = apply_filters(df, year, None, store, category)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    g = d.groupby("Channel")["Revenue"].sum()
    total = g.sum()
    value = {"revenue": {k: _r(v) for k, v in g.items()},
             "share_pct": {k: _r(v / total * 100) if total else None for k, v in g.items()},
             "total_revenue": _r(total)}
    cav = [REVENUE_NOT_PROFIT, "Share = channel revenue / total revenue of the same scope."]
    cav += _missing_revenue_caveat(d)
    if "Unknown store" in g.index:
        cav.append("Some sales rows have a Store ID that is not in the Stores table (channel 'Unknown store').")
    return _result(tool, value, "Sum of Revenue grouped by StoreType (Website / Brick & Mortar).", scope, len(d), cav)


def get_revenue_by_year(df, channel=None, store=None, category=None) -> dict:
    """Annual revenue and year-over-year change."""
    tool = "get_revenue_by_year"
    d, scope, err = apply_filters(df, None, channel, store, category)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    g = d.dropna(subset=["Year"]).groupby("Year")["Revenue"].sum().sort_index()
    rows, prev = [], None
    for y, v in g.items():
        rows.append({"year": int(y), "revenue": _r(v), "yoy_change": _r(v - prev) if prev is not None else None,
                     "yoy_change_pct": _r(_pct(v, prev)) if prev is not None else None})
        prev = v
    value = {"by_year": rows}
    if len(g) >= 2:
        value["first_to_last"] = {"from_year": int(g.index[0]), "to_year": int(g.index[-1]),
                                  "change": _r(g.iloc[-1] - g.iloc[0]), "change_pct": _r(_pct(g.iloc[-1], g.iloc[0]))}
    cav = [REVENUE_NOT_PROFIT, "Years are calendar years of the Sales Date."] + _undated_caveat(d) + _missing_revenue_caveat(d)
    return _result(tool, value, "Sum of Revenue by calendar year of Date; change vs. prior year.", scope, len(d), cav)


def get_channel_growth(df, start_year=None, end_year=None, category=None) -> dict:
    """Revenue growth of each channel between two years (default: first and last year in the data)."""
    tool = "get_channel_growth"
    yrs = allowed_values(df)["year"]
    if not yrs:
        return _result(tool, None, "", {}, 0, error="No dated sales rows in the data.")
    start_year = int(start_year) if start_year else yrs[0]
    end_year = int(end_year) if end_year else yrs[-1]
    for y in (start_year, end_year):
        if y not in yrs:
            return _result(tool, None, "", {}, 0, error=f"Year {y} not in the data. Available years: {yrs}.")
    d, scope, err = apply_filters(df, [start_year, end_year], None, None, category)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    p = d.pivot_table(index="Channel", columns="Year", values="Revenue", aggfunc="sum").reindex(columns=[start_year, end_year])
    rows = []
    for ch, r in p.iterrows():
        a, b = r.get(start_year), r.get(end_year)
        rows.append({"channel": ch, f"revenue_{start_year}": _r(a), f"revenue_{end_year}": _r(b),
                     "change": _r(b - a) if pd.notna(a) and pd.notna(b) else None,
                     "change_pct": _r(_pct(b, a))})
    rows.sort(key=lambda x: (x["change_pct"] is None, -(x["change_pct"] or 0)))
    value = {"start_year": start_year, "end_year": end_year, "channels": rows,
             "greatest_growth": rows[0]["channel"] if rows and rows[0]["change_pct"] is not None else None}
    scope = {"start_year": start_year, "end_year": end_year, "category": scope.get("category", "All")}
    cav = [REVENUE_NOT_PROFIT, "Growth compares two single years; it does not describe the years in between."]
    return _result(tool, value, "Per channel: (Revenue in end year - Revenue in start year) / Revenue in start year.",
                   scope, len(d), cav + _missing_revenue_caveat(d))


def get_store_trend(df, start_year=None, end_year=None, category=None, channel=None) -> dict:
    """Revenue change for every store between two years, sorted from largest decline to largest growth."""
    tool = "get_store_trend"
    yrs = allowed_values(df)["year"]
    if not yrs:
        return _result(tool, None, "", {}, 0, error="No dated sales rows in the data.")
    start_year = int(start_year) if start_year else yrs[0]
    end_year = int(end_year) if end_year else yrs[-1]
    for y in (start_year, end_year):
        if y not in yrs:
            return _result(tool, None, "", {}, 0, error=f"Year {y} not in the data. Available years: {yrs}.")
    if start_year == end_year:
        return _result(tool, None, "", {}, 0, error="Start year and end year must be different.")
    d, scope, err = apply_filters(df, [start_year, end_year], channel, None, category)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    p = d.pivot_table(index=["Store", "Channel"], columns="Year", values="Revenue", aggfunc="sum")
    rows, not_comparable = [], []
    for (st, ch), r in p.iterrows():
        a, b = r.get(start_year, np.nan), r.get(end_year, np.nan)
        if pd.isna(a) or pd.isna(b) or a == 0:
            not_comparable.append(st)
            continue
        rows.append({"store": st, "channel": ch, f"revenue_{start_year}": _r(a), f"revenue_{end_year}": _r(b),
                     "change": _r(b - a), "change_pct": _r(_pct(b, a))})
    rows.sort(key=lambda x: x["change_pct"])
    declined = [x for x in rows if x["change_pct"] < 0]
    value = {"start_year": start_year, "end_year": end_year, "stores": rows,
             "stores_declined": len(declined), "stores_grew_or_flat": len(rows) - len(declined),
             "largest_pct_decline": declined[0] if declined else None,
             "largest_pct_growth": rows[-1] if rows and rows[-1]["change_pct"] > 0 else None}
    cav = [REVENUE_NOT_PROFIT, "A revenue decline alone does not show whether a store is unprofitable."]
    if not declined:
        cav.append("No store declined between these years; there is no 'greatest decline' to report.")
    if not_comparable:
        cav.append(f"Not comparable (missing or zero revenue in one of the years): {', '.join(not_comparable)}.")
    scope = {"start_year": start_year, "end_year": end_year,
             "channel": scope.get("channel", "All"), "category": scope.get("category", "All")}
    return _result(tool, value, "Per store: (Revenue end year - Revenue start year) / Revenue start year.",
                   scope, len(d), cav + _missing_revenue_caveat(d))


def get_monthly_revenue_share(df, year=None, channel=None, store=None, category=None) -> dict:
    """Revenue by calendar month and each month's share of the in-scope total."""
    tool = "get_monthly_revenue_share"
    d, scope, err = apply_filters(df, year, channel, store, category)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    dd = d.dropna(subset=["Month"])
    g = dd.groupby("Month")["Revenue"].sum().reindex(range(1, 13), fill_value=0)
    total = g.sum()
    rows = [{"month": MONTHS[m - 1], "revenue": _r(v), "share_pct": _r(v / total * 100) if total else None}
            for m, v in g.items()]
    top = sorted(rows, key=lambda x: -(x["revenue"] or 0))
    value = {"by_month": rows, "highest_month": top[0]["month"] if total else None,
             "lowest_month": top[-1]["month"] if total else None, "total_revenue": _r(total)}
    n_years = dd["Year"].nunique()
    cav = [REVENUE_NOT_PROFIT,
           f"Denominator: total revenue of the same scope across all 12 months"
           f"{' and ' + str(n_years) + ' years (same as Power BI percent of grand total)' if n_years > 1 else ''}."]
    return _result(tool, value, "Sum of Revenue by calendar month; share = month revenue / scope total.",
                   scope, len(d), cav + _undated_caveat(d) + _missing_revenue_caveat(d))


def get_category_performance(df, year=None, channel=None, store=None) -> dict:
    """Revenue by product category, with each category's change from first to last year in scope."""
    tool = "get_category_performance"
    d, scope, err = apply_filters(df, year, channel, store, None)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    total = d["Revenue"].sum()
    g = d.groupby("Category")["Revenue"].sum().sort_values(ascending=False)
    p = d.dropna(subset=["Year"]).pivot_table(index="Category", columns="Year", values="Revenue", aggfunc="sum")
    yrs = sorted(p.columns)
    rows = []
    for cat, v in g.items():
        rec = {"category": cat, "revenue": _r(v), "share_pct": _r(v / total * 100) if total else None}
        if len(yrs) >= 2 and cat in p.index:
            a, b = p.loc[cat, yrs[0]], p.loc[cat, yrs[-1]]
            rec.update({"first_year": int(yrs[0]), "last_year": int(yrs[-1]), "change_pct_first_to_last": _r(_pct(b, a))})
            rec["by_year"] = {int(y): _r(p.loc[cat, y]) for y in yrs}
        rows.append(rec)
    growth = [r for r in rows if r.get("change_pct_first_to_last") is not None]
    growth.sort(key=lambda r: -r["change_pct_first_to_last"])
    value = {"categories": rows, "total_revenue": _r(total),
             "fastest_growing": growth[0]["category"] if growth else None,
             "slowest_growing": growth[-1]["category"] if growth else None}
    return _result(tool, value,
                   "Sum of Revenue grouped by Category (via Category ID).", scope, len(d),
                   [REVENUE_NOT_PROFIT] + _missing_revenue_caveat(d))


def survey_store_year(model_survey: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Sales to store-year FIRST, then join the survey (both are one row per store-year)."""
    sy = (sales.dropna(subset=["StoreYear"]).groupby("StoreYear", as_index=False)
          .agg(Revenue=("Revenue", "sum"), Store=("Store", "first"), Channel=("Channel", "first")))
    sv = model_survey.drop_duplicates("Survey ID")
    out = sv.merge(sy, left_on="Survey ID", right_on="StoreYear", how="left", validate="1:1")
    return out


def get_satisfaction_vs_revenue(df, survey, year=None, store=None) -> dict:
    """Association between yearly customer satisfaction and the same store's revenue that year."""
    tool = "get_satisfaction_vs_revenue"
    d, scope, err = apply_filters(df, year, None, store, None)
    if err:
        return _result(tool, None, "", {}, 0, error=err)
    sy = survey_store_year(survey, d)
    if _as_list(year):
        sy = sy[sy["Survey Year"].isin([int(y) for y in _as_list(year)])]
    if _as_list(store):
        sy = sy[sy["Store"].isin(scope["store"] if isinstance(scope["store"], list) else [scope["store"]])]
    usable = sy.dropna(subset=["Satisfaction", "Revenue"])
    n_missing = int(sy["Satisfaction"].isna().sum())
    corr = usable["Satisfaction"].corr(usable["Revenue"]) if len(usable) >= 3 else None
    corr_int = usable["Interest"].corr(usable["Revenue"]) if len(usable) >= 3 else None
    per_store = (usable.groupby("Store").agg(avg_satisfaction=("Satisfaction", "mean"), total_revenue=("Revenue", "sum"))
                 .sort_values("avg_satisfaction", ascending=False).reset_index())
    value = {"pearson_r_satisfaction_revenue": _r(corr, 3), "pearson_r_interest_revenue": _r(corr_int, 3),
             "store_years_used": int(len(usable)), "store_years_missing_satisfaction": n_missing,
             "per_store": [{"store": r.Store, "avg_satisfaction": _r(r.avg_satisfaction), "total_revenue": _r(r.total_revenue)}
                           for r in per_store.itertuples()]}
    cav = ["Correlation shows association only; it does not show that satisfaction causes revenue (or the reverse).",
           "Other factors (market size, location, store type) are not controlled for.",
           "Survey responses come from customers who still shop at the store; lost customers are not represented.",
           f"{n_missing} store-year(s) have no satisfaction score (e.g. the website is not surveyed) and were excluded."]
    if corr is None:
        cav.append("Fewer than 3 usable store-years: no correlation is reported.")
    return _result(tool, value, "Sales summed to store-year, joined 1:1 to Survey on StoreYear = Survey ID; "
                   "Pearson correlation across store-years.", scope, len(d), cav)


def get_data_coverage(df, survey) -> dict:
    """What the data contains - and what it cannot answer (profit, costs, customers...)."""
    tool = "get_data_coverage"
    av = allowed_values(df)
    value = {
        "available_measures": ["Revenue (monthly, by store, product, category)",
                               "Customer satisfaction score 0-5 and interest score (yearly, per physical store)"],
        "dimensions": {"years": av["year"], "channels": av["channel"], "stores": len(av["store"]),
                       "categories": av["category"]},
        "NOT_available": ["costs / expenses / cost of goods", "profit or margin", "rent or lease obligations",
                          "staffing / payroll", "units sold or prices", "customer counts or traffic",
                          "marketing spend", "competitor data"],
    }
    cav = ["Questions about profitability, closing or opening stores, or ROI cannot be answered from revenue alone.",
           REVENUE_NOT_PROFIT]
    return _result(tool, value, "Inventory of the fields in the loaded tables.", {"year": "All"}, len(df), cav)


def get_data_quality_report(model) -> dict:
    """Missing values, duplicates, orphan keys and other potential problems in the loaded data."""
    tool = "get_data_quality_report"
    s = model.sales
    issues = []

    def add(table, check, count, detail="", severity="warning"):
        issues.append({"table": table, "check": check, "count": int(count), "detail": detail,
                       "severity": severity if count else "ok"})

    for c in ["Sales ID", "Date", "Store ID", "StoreYear", "Category ID", "Product ID", "Revenue"]:
        add("Sales", f"Blank / invalid {c}", s[c].isna().sum())
    add("Sales", "Duplicate Sales ID", s["Sales ID"].duplicated(keep=False).sum() if s["Sales ID"].notna().any() else 0)
    nat = s[["Store ID", "Product ID", "Date"]].dropna()
    add("Sales", "Duplicate store + product + month (same grain twice)", nat.duplicated(keep=False).sum())
    add("Sales", "Negative revenue", (s["Revenue"] < 0).sum(), severity="error")
    add("Sales", "Zero revenue", (s["Revenue"] == 0).sum(), severity="info")
    add("Sales", "Store ID not in Stores table", (s["Store ID"].notna() & s["StoreType"].isna()).sum(), severity="error")
    add("Sales", "Product ID not in Products table", (s["Product ID"].notna() & s["Product"].isna()).sum())
    add("Sales", "Category ID not in Categories table", s["Category"].str.startswith("Unknown category").sum())
    exp = s["Store ID"] + "_" + (s["Year"].astype("Int64") % 100).astype("string").str.zfill(2)
    add("Sales", "StoreYear inconsistent with Store ID + Date year", (s["StoreYear"].notna() & exp.notna() & (s["StoreYear"] != exp)).sum())
    pc = s.dropna(subset=["Product ID", "Category ID"]).groupby("Product ID")["Category ID"].nunique()
    add("Sales", "Product IDs filed under more than one category", (pc > 1).sum())
    med = s.groupby(["Store ID", "Product ID"])["Revenue"].transform("median")
    ratio = s["Revenue"] / med
    odd = (ratio > 10) | (ratio < 0.1)
    add("Sales", "Unusual revenue (>10x or <1/10 of the same store+product's median month)", odd.sum(),
        ", ".join(s.loc[odd, "Sales ID"].astype(str).head(8)), severity="info")

    st = model.stores
    add("Stores", "Duplicate ID (raw file)", model.raw_counts.get("Stores", len(st)) - len(st), severity="error")
    phys = st[st["StoreType"] != "Website"]
    dup_city = phys["City"].notna() & phys["City"].duplicated(keep=False)
    add("Stores", "Cities shared by more than one store", dup_city.sum(),
        ", ".join(sorted(phys.loc[dup_city, "Store"])) + " - stores are labelled by City (ID) so they are not merged",
        severity="info")
    add("Stores", "Stores with no sales rows", (~st["ID"].isin(s["Store ID"])).sum())

    pr = model.products
    dup_name = pr["Product"].duplicated(keep=False)
    add("Products", "Product names used by more than one Product ID", dup_name.sum(),
        ", ".join(sorted(pr.loc[dup_name, "Product"] + " (" + pr.loc[dup_name, "Product ID"] + ")")) +
        " - products are grouped by ID, never by name", severity="info")

    sv = model.survey
    add("Survey", "Missing satisfaction score", sv["Satisfaction"].isna().sum(),
        ", ".join(sv.loc[sv["Satisfaction"].isna(), "Survey ID"].astype(str).head(8)), severity="info")
    add("Survey", "Satisfaction outside 0-5", ((sv["Satisfaction"] < 0) | (sv["Satisfaction"] > 5)).sum(), severity="error")
    add("Survey", "Duplicate Survey ID", sv["Survey ID"].duplicated(keep=False).sum(), severity="error")
    add("Survey", "Survey ID with no matching sales", (~sv["Survey ID"].isin(s["StoreYear"])).sum())

    for w in model.warnings:
        issues.append({"table": "Load", "check": w, "count": 1, "detail": "", "severity": "warning"})
    flagged = [i for i in issues if i["count"]]
    return _result(tool, {"issues": issues, "flagged_checks": len(flagged)},
                   "Rule-based checks on the loaded tables (no data is changed).",
                   {"year": "All"}, len(s), ["Checks flag potential problems; they do not correct the data."])
