"""E-Presso BI Analyst - Streamlit app.

Layout only. All calculations live in epresso/analytics.py so the dashboard and
the assistant use exactly the same, tested definitions.
"""
from __future__ import annotations

import json

import altair as alt
import pandas as pd
import streamlit as st

from epresso import agent as G
from epresso import analytics as A
from epresso.data_loader import GRAIN, DataError, load

st.set_page_config(page_title="E-Presso BI Analyst", page_icon="☕", layout="wide")
# KPI values: shrink with the window instead of being cut off with "..."
st.markdown("<style>[data-testid='stMetricValue']{font-size:clamp(1.15rem,2.3vw,2.25rem);}"
            "[data-testid='stMetricValue'] > div{overflow:visible;text-overflow:clip;}</style>",
            unsafe_allow_html=True)

QUESTION_LIMIT = 15
DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]
MONTHS = A.MONTHS
LINE_COLORS = {"All channels": "#888888", "Website": "#2E6F9E", "Brick & Mortar": "#C8792B", "Unknown store": "#999999"}
CH_COLORS = alt.Scale(domain=["Website", "Brick & Mortar", "Unknown store"], range=["#2E6F9E", "#C8792B", "#999999"])


# ------------------------------------------------------------------ data load
@st.cache_data(show_spinner="Loading and checking the E-Presso data...", max_entries=4)
def get_model(payload: tuple):
    """Cached on the uploaded file CONTENTS (bytes), so a modified file always recalculates."""
    return load(list(payload))


def money(x):
    return "—" if x is None or pd.isna(x) else (f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}")


def secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:  # no secrets file configured
        return default


st.sidebar.title("☕ E-Presso BI Analyst")
with st.sidebar.expander("📂 Data source", expanded=False):
    st.caption("The app starts with the original course files. Upload updated copies (same file and column names) "
               "to recalculate everything - no code changes. Any file you do not upload falls back to the original.")
    uploads = st.file_uploader("Upload Support_EX_B_Sales.accdb, Support_EX_B_Stores.csv, Support_EX_B_Survey.xlsx "
                               "(or a table exported as .csv/.xlsx)", type=["accdb", "csv", "txt", "xlsx"],
                               accept_multiple_files=True)
payload = tuple(sorted((f.name, f.getvalue()) for f in (uploads or [])))

try:
    model = get_model(payload)
except DataError as e:
    st.error(f"**The data could not be loaded.** {e}")
    st.info("Fix the file and upload it again. Required columns: "
            "Sales (Sales ID, Date, Store ID, StoreYear, Category ID, Product ID, Revenue); "
            "Stores (ID, City, State, StoreType, Market, Location); Survey sheet 'Survey Results' "
            "(Survey ID, Store ID, Year, Satisfaction, Interest); Products (Product ID, Product); "
            "Categories (Category ID, Category).")
    st.stop()

sales_all = model.sales
uploaded_any = any(v.startswith("UPLOADED") for v in model.sources.values())
data_label = (f"{len(sales_all):,} sales rows · total {money(sales_all['Revenue'].sum())} · "
              f"{'UPLOADED data' if uploaded_any else 'original course data'}")

# --------------------------------------------------------------------- filters
av = A.allowed_values(sales_all)
fk = model.fingerprint  # widget keys depend on the data, so filters reset when new data is loaded
st.sidebar.markdown("### Filters")
st.sidebar.caption("Empty = all. Every chart, KPI and table below uses these filters.")
f_years = st.sidebar.multiselect("Year", av["year"], key=f"y{fk}")
f_channels = st.sidebar.multiselect("Sales channel", av["channel"], key=f"c{fk}")
store_opts = sorted(sales_all.loc[sales_all["Channel"].isin(f_channels) if f_channels else slice(None), "Store"].dropna().unique())
f_stores = st.sidebar.multiselect("Store", store_opts, key=f"s{fk}")
f_cats = st.sidebar.multiselect("Product category", av["category"], key=f"k{fk}")
filters = {"year": f_years or None, "channel": f_channels or None, "store": f_stores or None, "category": f_cats or None}
df, scope, err = A.apply_filters(sales_all, **filters)
if err:
    st.error(err)
    st.stop()
scope_line = G.scope_text(scope, from_sidebar=True).replace(" (from the dashboard filters).", "")
st.sidebar.markdown("---")
st.sidebar.caption(f"**Loaded:** {data_label}")
for k, v in model.sources.items():
    st.sidebar.caption(f"{k}: {v}")

# ---------------------------------------------------------------------- header
st.title("E-Presso Revenue Dashboard")
st.caption(f"{scope_line} · Revenue in US$, 2025–2029 monthly sales by store × product. "
           f"Revenue is sales revenue, **not profit** (no cost data).")
if uploaded_any:
    st.info("📤 Using **uploaded** data: " + "; ".join(f"{k} ← {v.replace('UPLOADED: ', '')}"
                                                       for k, v in model.sources.items() if v.startswith("UPLOADED")))

tabs = st.tabs(["📊 Overview", "📈 Trends & seasonality", "🏬 Stores", "⭐ Customer survey",
                "🧪 Data quality & model", "🤖 Analytical assistant"])

# ==================================================================== OVERVIEW
with tabs[0]:
    summ = A.get_revenue_summary(df)["value"]
    by_ch = A.get_revenue_by_channel(df)["value"]
    by_y = A.get_revenue_by_year(df)["value"]["by_year"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total revenue", money(summ["total_revenue"]), help="Sum of Sales.Revenue for the filtered rows")
    for col, ch in ((c2, "Website"), (c3, "Brick & Mortar")):
        amt = by_ch["revenue"].get(ch)
        share = by_ch["share_pct"].get(ch)
        col.metric(f"{ch} revenue", money(amt), f"{share:.1f}% of total" if share is not None else None, delta_color="off")
    if len(by_y) >= 2 and by_y[-1]["yoy_change_pct"] is not None:
        c4.metric(f"Growth {by_y[-2]['year']}→{by_y[-1]['year']}", f"{by_y[-1]['yoy_change_pct']:+.1f}%",
                  money(by_y[-1]["yoy_change"]))
    else:
        c4.metric("Sales rows in scope", f"{summ['sales_rows']:,}")
    if summ["sales_rows"] == 0:
        st.warning("No sales rows match the current filters.")

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Total revenue by store type")
        ch_df = pd.DataFrame([{"Channel": k, "Revenue": v, "Share": by_ch["share_pct"][k]} for k, v in by_ch["revenue"].items()])
        if len(ch_df):
            bar = alt.Chart(ch_df).mark_bar().encode(
                y=alt.Y("Channel:N", title=None, sort="-x"), x=alt.X("Revenue:Q", title="Revenue (US$)", axis=alt.Axis(format="$,.0s")),
                color=alt.Color("Channel:N", scale=CH_COLORS, legend=None),
                tooltip=["Channel", alt.Tooltip("Revenue:Q", format="$,.0f"), alt.Tooltip("Share:Q", format=".2f", title="Share %")])
            text = bar.mark_text(align="left", dx=4).encode(text=alt.Text("Revenue:Q", format="$,.0f"))
            st.altair_chart((bar + text).properties(height=220), width="stretch")
    with right:
        st.subheader("Total revenue by year and store type")
        yc = df.dropna(subset=["Year"]).groupby(["Year", "Channel"], as_index=False)["Revenue"].sum()
        yt = df.dropna(subset=["Year"]).groupby("Year", as_index=False)["Revenue"].sum().assign(Channel="All channels")
        ydf = pd.concat([yc, yt])
        if len(ydf):
            ydf["Year"] = ydf["Year"].astype(int).astype(str)
            line = alt.Chart(ydf).mark_line(point=True).encode(
                x=alt.X("Year:O", title="Year"), y=alt.Y("Revenue:Q", title="Revenue (US$)", axis=alt.Axis(format="$,.2s")),
                color=alt.Color("Channel:N", scale=alt.Scale(domain=[c for c in LINE_COLORS if c in set(ydf["Channel"])],
                                                             range=[LINE_COLORS[c] for c in LINE_COLORS if c in set(ydf["Channel"])]), title=None),
                tooltip=["Year", "Channel", alt.Tooltip("Revenue:Q", format="$,.0f")])
            st.altair_chart(line.properties(height=260), width="stretch")
    st.markdown("**Revenue by year (table)**")
    st.dataframe(pd.DataFrame(by_y).rename(columns={"year": "Year", "revenue": "Revenue", "yoy_change": "Change vs prior year",
                                                    "yoy_change_pct": "Change %"}),
                 hide_index=True, width="stretch",
                 column_config={"Year": st.column_config.NumberColumn(format="%d"),
                                "Revenue": st.column_config.NumberColumn(format="dollar"),
                                "Change vs prior year": st.column_config.NumberColumn(format="dollar"),
                                "Change %": st.column_config.NumberColumn(format="%.2f%%")})

# ===================================================================== TRENDS
with tabs[1]:
    st.subheader("Monthly revenue pattern")
    mshare = A.get_monthly_revenue_share(df)
    st.caption(mshare["caveats"][1] if len(mshare["caveats"]) > 1 else "")
    metric = st.radio("Show", ["Revenue (US$)", "% of total revenue in scope"], horizontal=True, key="mmetric")
    mdf = pd.DataFrame(mshare["value"]["by_month"])
    ycol, fmt, title = (("revenue", "$,.0f", "Revenue (US$)") if metric.startswith("Revenue")
                        else ("share_pct", ".2f", "% of total revenue"))
    mchart = alt.Chart(mdf).mark_bar(color="#2E6F9E").encode(
        x=alt.X("month:N", sort=MONTHS, title="Month"), y=alt.Y(f"{ycol}:Q", title=title),
        tooltip=["month", alt.Tooltip("revenue:Q", format="$,.0f", title="Revenue"), alt.Tooltip("share_pct:Q", format=".2f", title="% of total")])
    st.altair_chart((mchart + mchart.mark_text(dy=-6).encode(text=alt.Text(f"{ycol}:Q", format=fmt if ycol == "share_pct" else "$,.2s")))
                    .properties(height=300), width="stretch")
    if mshare["value"]["highest_month"]:
        st.caption(f"Highest month: **{mshare['value']['highest_month']}** · lowest: **{mshare['value']['lowest_month']}**.")

    st.subheader("Revenue by product category")
    cat = A.get_category_performance(df)["value"]
    cdf = df.dropna(subset=["Year"]).groupby(["Year", "Category"], as_index=False)["Revenue"].sum()
    if len(cdf):
        cdf["Year"] = cdf["Year"].astype(int).astype(str)
        cl = alt.Chart(cdf).mark_line(point=True).encode(
            x=alt.X("Year:O"), y=alt.Y("Revenue:Q", title="Revenue (US$)", axis=alt.Axis(format="$,.2s")),
            color=alt.Color("Category:N", title="Category"), tooltip=["Year", "Category", alt.Tooltip("Revenue:Q", format="$,.0f")])
        st.altair_chart(cl.properties(height=280), width="stretch")
    st.dataframe(pd.DataFrame(cat["categories"]).drop(columns=["by_year"], errors="ignore")
                 .rename(columns={"category": "Category", "revenue": "Revenue", "share_pct": "Share %",
                                  "change_pct_first_to_last": "Change % (first→last year)",
                                  "first_year": "First year", "last_year": "Last year"}),
                 hide_index=True, width="stretch",
                 column_config={"Revenue": st.column_config.NumberColumn(format="dollar"),
                                "Share %": st.column_config.NumberColumn(format="%.2f%%"),
                                "Change % (first→last year)": st.column_config.NumberColumn(format="%.2f%%"),
                                "First year": st.column_config.NumberColumn(format="%d"),
                                "Last year": st.column_config.NumberColumn(format="%d")})

# ===================================================================== STORES
with tabs[2]:
    yrs_in = sorted(int(y) for y in df["Year"].dropna().unique())
    st.subheader("Store revenue change between two years")
    if len(yrs_in) >= 2:
        a, b = st.columns(2)
        sy = a.selectbox("From year", yrs_in, index=0, key=f"sy{fk}")
        ey = b.selectbox("To year", yrs_in, index=len(yrs_in) - 1, key=f"ey{fk}")
        if sy == ey:
            st.warning("Choose two different years.")
        else:
            trend = A.get_store_trend(df, start_year=sy, end_year=ey)
            if trend.get("error"):
                st.error(trend["error"])
            else:
                tv = trend["value"]
                tdf = pd.DataFrame(tv["stores"])
                if len(tdf):
                    tdf = tdf.rename(columns={"store": "Store", "channel": "Channel", f"revenue_{sy}": f"Revenue {sy}",
                                              f"revenue_{ey}": f"Revenue {ey}", "change": "Change", "change_pct": "Change %"})
                    st.caption(f"{tv['stores_declined']} of {len(tdf)} locations had lower revenue in {ey} than in {sy}. "
                               + (f"Largest decline: **{tv['largest_pct_decline']['store']}** "
                                  f"({tv['largest_pct_decline']['change_pct']:+.1f}%)." if tv["largest_pct_decline"] else
                                  "No location declined."))
                    sc = alt.Chart(tdf).mark_bar().encode(
                        y=alt.Y("Store:N", sort="x", title=None), x=alt.X("Change %:Q", title=f"Revenue change {sy}→{ey} (%)"),
                        color=alt.condition("datum['Change %'] < 0", alt.value("#B03A2E"), alt.value("#2E7D32")),
                        tooltip=["Store", alt.Tooltip(f"Revenue {sy}:Q", format="$,.0f"), alt.Tooltip(f"Revenue {ey}:Q", format="$,.0f"),
                                 alt.Tooltip("Change %:Q", format=".2f")])
                    st.altair_chart(sc.properties(height=max(250, 22 * len(tdf))), width="stretch")
                    st.dataframe(tdf, hide_index=True, width="stretch",
                                 column_config={f"Revenue {sy}": st.column_config.NumberColumn(format="dollar"),
                                                f"Revenue {ey}": st.column_config.NumberColumn(format="dollar"),
                                                "Change": st.column_config.NumberColumn(format="dollar"),
                                                "Change %": st.column_config.NumberColumn(format="%.2f%%")})
                for c in trend["caveats"][1:]:
                    st.caption(f"ⓘ {c}")
    else:
        st.info("Select at least two years (or clear the Year filter) to compare stores over time.")

    st.subheader("Drill down: market → city")
    mk = df.groupby("Market", as_index=False)["Revenue"].sum().sort_values("Market")
    st.altair_chart(alt.Chart(mk).mark_bar(color="#6A4C93").encode(
        x=alt.X("Market:N", title="Market size"), y=alt.Y("Revenue:Q", title="Revenue (US$)", axis=alt.Axis(format="$,.2s")),
        tooltip=["Market", alt.Tooltip("Revenue:Q", format="$,.0f")]).properties(height=240), width="stretch")
    markets = mk["Market"].dropna().tolist()
    if markets:
        pick = st.selectbox("Choose a market to see its stores", markets, key=f"mk{fk}")
        sub = df[df["Market"] == pick].dropna(subset=["Year"]).groupby(["Year", "Store"], as_index=False)["Revenue"].sum()
        sub["Year"] = sub["Year"].astype(int).astype(str)
        st.altair_chart(alt.Chart(sub).mark_line(point=True).encode(
            x="Year:O", y=alt.Y("Revenue:Q", title="Revenue (US$)", axis=alt.Axis(format="$,.2s")), color=alt.Color("Store:N"),
            tooltip=["Store", "Year", alt.Tooltip("Revenue:Q", format="$,.0f")]).properties(height=260), width="stretch")

# ===================================================================== SURVEY
with tabs[3]:
    st.subheader("Total revenue vs. customer satisfaction (one point per store-year)")
    sat = A.get_satisfaction_vs_revenue(df, model.survey)
    sy_df = A.survey_store_year(model.survey, df).dropna(subset=["Satisfaction", "Revenue"])
    if f_years:
        sy_df = sy_df[sy_df["Survey Year"].isin(f_years)]
    if len(sy_df):
        pts = alt.Chart(sy_df).mark_circle(size=70, opacity=0.75).encode(
            x=alt.X("Satisfaction:Q", title="Customer satisfaction (0–5)", scale=alt.Scale(domain=[0, 5])),
            y=alt.Y("Revenue:Q", title="Store revenue that year (US$)", axis=alt.Axis(format="$,.2s")),
            color=alt.Color("Store:N", legend=None),
            tooltip=["Store", "Survey Year", "Satisfaction", "Interest", alt.Tooltip("Revenue:Q", format="$,.0f")])
        trend_line = pts.transform_regression("Satisfaction", "Revenue").mark_line(color="#444", strokeDash=[5, 3])
        st.altair_chart((pts + trend_line).properties(height=360), width="stretch")
        r = sat["value"]["pearson_r_satisfaction_revenue"]
        st.markdown(f"Correlation r = **{r}** across {sat['value']['store_years_used']} store-years "
                    f"({sat['value']['store_years_missing_satisfaction']} store-years without a score excluded)."
                    if r is not None else "Not enough survey data for a correlation.")
    else:
        st.info("No surveyed store-years in the current filters (the website is not surveyed).")
    for c in sat.get("caveats", []):
        st.caption(f"ⓘ {c}")
    st.markdown("**Stores: average satisfaction and total revenue (filtered years)**")
    ps = pd.DataFrame(sat["value"]["per_store"]) if sat.get("value") else pd.DataFrame()
    if len(ps):
        meta = model.stores.set_index("Store")[["State", "Location", "Market", "StoreType"]]
        ps = ps.join(meta, on="store").rename(columns={"store": "Store", "avg_satisfaction": "Avg satisfaction",
                                                       "total_revenue": "Total revenue"})
        st.dataframe(ps, hide_index=True, width="stretch",
                     column_config={"Total revenue": st.column_config.NumberColumn(format="dollar")})

# =============================================================== DATA QUALITY
with tabs[4]:
    st.subheader("Loaded tables")
    prof = []
    for name, tdf in (("Sales", model.sales), ("Stores", model.stores), ("Products", model.products),
                      ("Categories", model.categories), ("Survey", model.survey)):
        prof.append({"Table": name, "Source": model.sources.get(name), "Rows loaded": model.raw_counts.get(name),
                     "Rows used": len(tdf), "Blank cells": int(tdf.isna().sum().sum())})
    st.dataframe(pd.DataFrame(prof), hide_index=True, width="stretch")
    pick_t = st.selectbox("Preview a table", ["Sales", "Stores", "Products", "Categories", "Survey"])
    tmap = {"Sales": model.sales, "Stores": model.stores, "Products": model.products,
            "Categories": model.categories, "Survey": model.survey}
    pt = tmap[pick_t]
    st.dataframe(pt.head(200), width="stretch")
    st.dataframe(pd.DataFrame({"Column": pt.columns, "Type": [str(t) for t in pt.dtypes],
                               "Blank": pt.isna().sum().values, "Distinct": pt.nunique().values}),
                 hide_index=True, width="stretch")

    st.subheader("Grain of each table (what one row represents)")
    st.dataframe(pd.DataFrame(GRAIN), hide_index=True, width="stretch")
    st.subheader("Relationships and merge checks")
    st.markdown("""
- **Sales → Stores**: `Sales.Store ID` = `Stores.ID` (many-to-one). Used for channel, city, market.
- **Sales → Products**: `Product ID` (many-to-one). **Sales → Categories**: `Category ID` (many-to-one).
- **Sales → Survey**: `Sales.StoreYear` = `Survey.Survey ID`. Survey is one row per store-**year**, Sales is one row
  per store-product-**month**, so Sales is **summed to store-year first** and then joined 1:1. Joining the raw
  tables would attach the same survey row to 240 sales rows and make survey averages and counts misleading.
- Stores are labelled *City (ID)* because two stores are in Orlando; products are grouped by ID because three
  different products are named "Base Model".""")
    st.dataframe(pd.DataFrame(model.merge_log), hide_index=True, width="stretch",
                 column_config={"Revenue sum before": st.column_config.NumberColumn(format="dollar"),
                                "Revenue sum after": st.column_config.NumberColumn(format="dollar")})

    st.subheader("Data-quality checks")
    dq = A.get_data_quality_report(model)["value"]["issues"]
    dqdf = pd.DataFrame(dq)
    st.dataframe(dqdf.sort_values("count", ascending=False), hide_index=True, width="stretch")
    if model.warnings:
        for w in model.warnings:
            st.warning(w)

    st.subheader("Reconciliation (same total, four ways)")
    total = A.get_revenue_summary(sales_all)["value"]["total_revenue"]
    rec = pd.DataFrame([
        {"Method": "Sum of raw Sales.Revenue (before any join)", "Total": float(sales_all["Revenue"].sum())},
        {"Method": "get_revenue_summary()", "Total": total},
        {"Method": "Sum of get_revenue_by_channel()", "Total": sum(A.get_revenue_by_channel(sales_all)["value"]["revenue"].values())},
        {"Method": "Sum of get_monthly_revenue_share() months", "Total": A.get_monthly_revenue_share(sales_all)["value"]["total_revenue"]},
    ])
    rec["Matches"] = (rec["Total"] - rec["Total"].iloc[0]).abs() < 0.01
    st.dataframe(rec, hide_index=True, width="stretch",
                 column_config={"Total": st.column_config.NumberColumn(format="dollar")})
    st.caption("Undated rows (if any) are excluded from the monthly total - a mismatch on that line points to blank dates.")

# ================================================================== ASSISTANT
with tabs[5]:
    api_key = secret("GEMINI_API_KEY")
    model_names = [m for m in [secret("GEMINI_MODEL")] if m] + DEFAULT_MODELS
    st.subheader("Ask a business question")
    if api_key:
        st.success("Mode: **Language-model agent (Gemini function calling)**. The model can only choose among the "
                   "named analytical functions below; it cannot run code or change data. If the API fails or the free "
                   "quota runs out, answers switch to the rules-based assistant.")
    else:
        st.warning("Mode: **Rules-based assistant** (no Gemini API key configured). Questions are routed by keywords to "
                   "the same analytical functions. This is not a language model.")
    with st.expander("Functions the assistant may call"):
        st.table(pd.DataFrame([{"Function": k, "Parameters": ", ".join(v["params"]) or "—", "What it does": v["description"]}
                               for k, v in G.TOOLS.items()]))
    use_sidebar = st.toggle("Apply the dashboard filters to my questions", value=False,
                            help="Off: answers use the full dataset unless the question names a year/store/etc. "
                                 "On: unspecified parameters are filled from the sidebar filters.")
    st.caption(f"Scope for questions: {'the sidebar filters — ' + scope_line if use_sidebar else 'full dataset'} · "
               f"Data: {data_label}")

    ss = st.session_state
    ss.setdefault("history", [])
    ss.setdefault("n_questions", 0)
    examples = ["How much revenue did the website generate in 2028?",
                "Which store experienced the greatest percentage revenue decline?",
                "Which sales channel experienced the greatest revenue growth?",
                "Which E-Presso store is the most profitable?",
                "Does higher customer satisfaction cause higher revenue?",
                "Should E-Presso close its Chicago store?"]
    cols = st.columns(3)
    clicked = None
    for i, ex in enumerate(examples):
        if cols[i % 3].button(ex, key=f"ex{i}", width="stretch"):
            clicked = ex

    for t in ss["history"]:
        with st.chat_message("user"):
            st.markdown(t["question"])
        with st.chat_message("assistant"):
            st.caption(f"{t['mode']} · data at answer time: {t['data']}")
            if t["notice"]:
                st.warning(t["notice"])
            st.markdown(t["answer"])
            if t["unverified"]:
                st.error("⚠️ These numbers in the answer could not be matched to any tool result - treat them as "
                         "unverified: " + ", ".join(t["unverified"]))
            with st.expander(f"Tool-call log ({len(t['calls'])} call(s))"):
                if not t["calls"]:
                    st.write("No analytical function was called.")
                for c in t["calls"]:
                    st.markdown(f"**{c['tool']}**  ·  args `{json.dumps(c['args'], default=str)}`  ·  {c['ms']} ms")
                    st.json(c["result"], expanded=False)

    remaining = QUESTION_LIMIT - ss["n_questions"]
    typed = st.chat_input(f"Ask about E-Presso revenue ({remaining} question(s) left this session)",
                          disabled=remaining <= 0)
    q = typed or clicked
    if remaining <= 0:
        st.info(f"You have reached the limit of {QUESTION_LIMIT} questions for this session (it protects the free API "
                "quota). Refresh the page to start a new session.")
    elif q:
        ss["n_questions"] += 1
        with st.spinner("Calculating..."):
            turn = G.ask(q, model, api_key=api_key, model_names=model_names,
                         sidebar_filters={k: v for k, v in filters.items() if v}, use_sidebar=use_sidebar)
        ss["history"].append({"question": q, "mode": turn.mode, "answer": turn.answer, "calls": turn.calls,
                              "notice": turn.notice, "unverified": turn.unverified_numbers, "data": data_label})
        st.rerun()
    if ss["history"] and st.button("Clear conversation"):
        ss["history"] = []
        st.rerun()
