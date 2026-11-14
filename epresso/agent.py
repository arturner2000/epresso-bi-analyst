"""The analytical assistant: dispatcher + two routers.

    question --> router --> dispatcher --> analytics function --> result (tool contract)
                   |                                                   |
                   +-- rules-based keyword router (always available)    |
                   +-- Gemini function-calling router (if a key is set) <+  model only explains

Safety boundaries (see README):
* The model can only CHOOSE among the named functions in TOOLS and supply
  parameters; parameters are validated against values that exist in the data.
* No eval/exec, no model-written pandas or SQL, nothing that modifies data.
* Every call is logged (tool name, arguments, raw result) and shown in the UI.
* Numbers in a model answer are checked against the tool results; anything
  that cannot be matched is flagged to the user.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from . import analytics as A

# ---------------------------------------------------------------- tool registry
TOOLS = {
    "get_revenue_summary": {
        "fn": lambda m, **k: A.get_revenue_summary(m.sales, **k),
        "params": ["year", "channel", "store", "category"],
        "description": "Total revenue for any combination of year, channel (Website / Brick & Mortar), store and "
                       "product category. Use for 'how much revenue...' questions.",
    },
    "get_revenue_by_channel": {
        "fn": lambda m, **k: A.get_revenue_by_channel(m.sales, **k),
        "params": ["year", "store", "category"],
        "description": "Website vs brick-and-mortar revenue and each channel's share of the total.",
    },
    "get_revenue_by_year": {
        "fn": lambda m, **k: A.get_revenue_by_year(m.sales, **k),
        "params": ["channel", "store", "category"],
        "description": "Annual revenue with year-over-year change, optionally for one channel, store or category.",
    },
    "get_channel_growth": {
        "fn": lambda m, **k: A.get_channel_growth(m.sales, **k),
        "params": ["start_year", "end_year", "category"],
        "description": "Which sales channel grew most: revenue change of each channel between two years "
                       "(default first and last year in the data).",
    },
    "get_store_trend": {
        "fn": lambda m, **k: A.get_store_trend(m.sales, **k),
        "params": ["start_year", "end_year", "category", "channel"],
        "description": "Revenue change ($ and %) of every store between two years, sorted from largest decline to "
                       "largest growth; reports if no store declined.",
    },
    "get_monthly_revenue_share": {
        "fn": lambda m, **k: A.get_monthly_revenue_share(m.sales, **k),
        "params": ["year", "channel", "store", "category"],
        "description": "Revenue by calendar month and each month's percentage of the in-scope total (seasonality).",
    },
    "get_category_performance": {
        "fn": lambda m, **k: A.get_category_performance(m.sales, **k),
        "params": ["year", "channel", "store"],
        "description": "Revenue by product category with share and change from first to last year.",
    },
    "get_satisfaction_vs_revenue": {
        "fn": lambda m, **k: A.get_satisfaction_vs_revenue(m.sales, m.survey, **k),
        "params": ["year", "store"],
        "description": "Correlation between yearly customer satisfaction and the same store's revenue; per-store "
                       "averages. Association only - not causation.",
    },
    "get_data_quality_report": {
        "fn": lambda m, **k: A.get_data_quality_report(m),
        "params": [],
        "description": "Missing values, duplicates, orphan keys and other potential data problems.",
    },
    "get_data_coverage": {
        "fn": lambda m, **k: A.get_data_coverage(m.sales, m.survey),
        "params": [],
        "description": "What the data contains and what it CANNOT answer (no costs, profit, rent, staffing, "
                       "units or customer counts). Call this for profit, cost, closing-store or ROI questions.",
    },
}

PARAM_TYPES = {"year": "INTEGER", "start_year": "INTEGER", "end_year": "INTEGER",
               "channel": "STRING", "store": "STRING", "category": "STRING"}
MAX_TOOL_CALLS = 6


@dataclass
class Turn:
    question: str
    mode: str                      # "Gemini (LLM)" or "Rules-based"
    answer: str = ""
    calls: list = field(default_factory=list)   # [{tool, args, result, ms}]
    notice: str = ""                            # e.g. API failure fallback message
    unverified_numbers: list = field(default_factory=list)


# --------------------------------------------------------------------- dispatch
def dispatch(model, name: str, args: dict | None, log: list) -> dict:
    """The ONLY way the assistant runs code: look up a named function, validate args, run, log."""
    args = dict(args or {})
    t0 = time.perf_counter()
    if name not in TOOLS:
        result = {"tool": name, "error": f"Unknown tool '{name}'. Allowed: {', '.join(TOOLS)}."}
    else:
        allowed = TOOLS[name]["params"]
        bad = [k for k in args if k not in allowed]
        clean = {k: v for k, v in args.items() if k in allowed and v not in (None, "", [], "All")}
        try:
            result = TOOLS[name]["fn"](model, **clean)
        except Exception as e:  # a bug in a tool must not crash the chat
            result = {"tool": name, "error": f"{type(e).__name__}: {e}"}
        if bad:
            result.setdefault("caveats", []).append(f"Ignored unsupported parameter(s): {', '.join(bad)}.")
        args = clean
    log.append({"tool": name, "args": args, "result": result, "ms": round((time.perf_counter() - t0) * 1000, 1)})
    return result


# ------------------------------------------------------------------ formatting
def money(x):
    if x is None:
        return "n/a"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def pct(x):
    return "n/a" if x is None else f"{x:+.1f}%"


def scope_text(scope: dict | None, from_sidebar: bool) -> str:
    if not scope:
        return "Scope: full dataset."
    parts = []
    for k, v in scope.items():
        label = k.replace("_", " ")
        if v in ("All", None):
            continue
        parts.append(f"{label} = {', '.join(map(str, v)) if isinstance(v, list) else v}")
    s = "Scope: " + ("; ".join(parts) if parts else "all stores, all channels, all categories, all years")
    return s + (" (from the dashboard filters)." if from_sidebar else " (full dataset unless named in the question).")


# --------------------------------------------------------------- rules router
def _extract_params(q: str, model) -> dict:
    av = A.allowed_values(model.sales)
    ql = q.lower()
    p = {}
    years = [int(y) for y in re.findall(r"\b(20\d\d)\b", q) if int(y) in av["year"]]
    bad_years = [int(y) for y in re.findall(r"\b(20\d\d)\b", q) if int(y) not in av["year"]]
    if bad_years:
        p["_bad_years"] = bad_years
    if years:
        p["years"] = years
    if re.search(r"\b(website|online|web|e-?commerce)\b", ql):
        p["channel"] = "Website"
    elif re.search(r"brick|physical|in-store|retail store", ql):
        p["channel"] = "Brick & Mortar"
    stores = model.stores
    for _, r in stores.iterrows():
        if r["StoreType"] == "Website":
            continue
        if re.search(rf"\b{re.escape(str(r['ID']).lower())}\b", ql):
            p["store"] = r["ID"]
            break
        if r["City"] and re.search(rf"\b{re.escape(str(r['City']).lower())}\b", ql):
            p["store"] = r["City"]  # resolve_store reports ambiguity (e.g. two Orlando stores)
    for c in av["category"]:
        stem = c.lower().rstrip("s")
        if re.search(rf"\b{re.escape(stem)}", ql):
            p["category"] = c
            break
    return p


def route_rules(q: str, model) -> list[tuple[str, dict]]:
    """Keyword router: returns the list of (tool, args) to run, or [] if unsupported."""
    ql = q.lower()
    p = _extract_params(q, model)
    yrs = p.get("years", [])
    y = yrs[0] if len(yrs) == 1 else (yrs or None)
    start, end = (min(yrs), max(yrs)) if len(yrs) >= 2 else (None, None)
    base = {k: p[k] for k in ("channel", "store", "category") if k in p}
    plan = []

    if re.search(r"profit|margin|cost|expense|roi|return on|earn(ing)?s? after|lease|rent|clos(e|ing)|shut|open(ing)? a new", ql):
        plan.append(("get_data_coverage", {}))
        if "store" in p:
            plan.append(("get_revenue_by_year", {"store": p["store"], "category": p.get("category")}))
        if "store" in p or re.search(r"store|location", ql):
            plan.append(("get_store_trend", {"start_year": start, "end_year": end, "category": p.get("category")}))
        else:
            plan.append(("get_revenue_by_channel", {"year": y, "category": p.get("category")}))
        return plan
    if re.search(r"satisf|survey|interest score|happy|customer (rating|score)", ql):
        return [("get_satisfaction_vs_revenue", {"year": y, "store": p.get("store")})]
    if re.search(r"data quality|missing|duplicate|blank|null|problem.*data|data.*problem|error.*data|clean", ql):
        return [("get_data_quality_report", {})]
    if re.search(r"month|season|holiday|december|november|january|quarter", ql):
        return [("get_monthly_revenue_share", {"year": y, **base})]
    trend_words = r"grow|growth|grew|declin|drop|fell|fall|increase|decrease|change|trend|improv|worse"
    if re.search(trend_words, ql) and re.search(r"\bstores?\b|location|which (store|city)|city", ql) \
            and not re.search(r"channel|website vs|online vs", ql):
        if "store" in p and "which" not in ql:
            return [("get_revenue_by_year", {"store": p["store"], "category": p.get("category")})]
        return [("get_store_trend", {"start_year": start, "end_year": end, "category": p.get("category"),
                                     "channel": p.get("channel") if p.get("channel") == "Website" else None})]
    if re.search(trend_words, ql) and re.search(r"channel|website|online|brick", ql):
        if "channel" in p and "which" not in ql and " vs" not in ql and "compar" not in ql:
            return [("get_revenue_by_year", {"channel": p["channel"], "category": p.get("category")})]
        return [("get_channel_growth", {"start_year": start, "end_year": end, "category": p.get("category")})]
    if re.search(r"categor|product|best.?sell|top.?sell", ql) and "category" not in p:
        return [("get_category_performance", {"year": y, "channel": p.get("channel"), "store": p.get("store")})]
    if re.search(r"channel|website vs|online vs|vs\.? (the )?website|compare.*(website|online|brick)|(website|online).*(brick|stores)", ql):
        return [("get_revenue_by_channel", {"year": y, "store": p.get("store"), "category": p.get("category")})]
    if re.search(r"by year|each year|per year|annual|yearly|over time|trend|growth|grow", ql):
        return [("get_revenue_by_year", base)]
    if re.search(r"revenue|sales|sell|sold|how much|total|earn|make|bring in", ql) or "_bad_years" in p:
        if "_bad_years" in p:
            return [("get_revenue_summary", {"year": p["_bad_years"][0], **base})]
        return [("get_revenue_summary", {"year": yrs or None, **base})]
    if "store" in p and re.search(r"perform|\bdo\b|\bdid\b|doing|results?|overview|summary|how (is|was|are)", ql):
        # a store is named with a performance question but no other intent matched: that store's yearly revenue
        return [("get_revenue_by_year", base)]
    return []


def _fill_from_sidebar(plan, sidebar: dict):
    """When the user chose 'apply dashboard filters', fill any parameter the question did not set."""
    out = []
    for tool, args in plan:
        allowed = TOOLS[tool]["params"]
        a = dict(args)
        for k, v in (sidebar or {}).items():
            if k in allowed and a.get(k) in (None, [], "") and v:
                a[k] = v
        yrs = sorted(int(y) for y in (sidebar or {}).get("year") or [])
        if "start_year" in allowed and len(yrs) >= 2 and not a.get("start_year") and not a.get("end_year"):
            a["start_year"], a["end_year"] = yrs[0], yrs[-1]
        out.append((tool, a))
    return out


CAPABILITIES = (
    "I can answer questions about E-Presso **revenue** using these functions: total revenue for any year/channel/"
    "store/category; website vs. brick-and-mortar; revenue by year; which channel grew most; store-by-store "
    "growth or decline; monthly seasonality; category performance; satisfaction vs. revenue (association only); "
    "data quality; and what the data cannot answer (costs, profit, rent, staffing)."
)


def _findings_for(res: dict) -> list[str]:
    """Plain-language statements built ONLY from fields in a tool result."""
    t, v = res.get("tool"), res.get("value") or {}
    if res.get("error"):
        return [f"The request could not be calculated: {res['error']}"]
    f = []
    if t == "get_revenue_summary":
        f.append(f"Total revenue: **{money(v['total_revenue'])}** from {v['sales_rows']:,} sales rows "
                 f"({v['stores_in_scope']} store(s), years {', '.join(map(str, v['years_in_scope'])) or 'none'}).")
    elif t == "get_revenue_by_channel":
        for ch, amt in sorted(v["revenue"].items(), key=lambda x: -x[1]):
            f.append(f"{ch}: **{money(amt)}** ({v['share_pct'][ch]:.2f}% of {money(v['total_revenue'])}).")
    elif t == "get_revenue_by_year":
        f.append("Revenue by year: " + "; ".join(f"{r['year']}: {money(r['revenue'])}"
                                                 + (f" ({pct(r['yoy_change_pct'])} vs prior year)" if r['yoy_change_pct'] is not None else "")
                                                 for r in v["by_year"]) + ".")
        if v.get("first_to_last"):
            fl = v["first_to_last"]
            f.append(f"From {fl['from_year']} to {fl['to_year']}: {money(fl['change'])} ({pct(fl['change_pct'])}).")
    elif t == "get_channel_growth":
        sy, ey = v["start_year"], v["end_year"]
        for r in v["channels"]:
            f.append(f"{r['channel']}: {money(r.get(f'revenue_{sy}'))} in {sy} -> "
                     f"{money(r.get(f'revenue_{ey}'))} in {ey} ({pct(r['change_pct'])}).")
        if v.get("greatest_growth"):
            f.append(f"Greatest growth: **{v['greatest_growth']}**.")
    elif t == "get_store_trend":
        sy, ey = v["start_year"], v["end_year"]
        f.append(f"{v['stores_declined']} of {len(v['stores'])} store(s) had lower revenue in {ey} than in {sy}.")
        if v["largest_pct_decline"]:
            d = v["largest_pct_decline"]
            f.append(f"Largest % decline: **{d['store']}**, {money(d[f'revenue_{sy}'])} -> {money(d[f'revenue_{ey}'])} "
                     f"({pct(d['change_pct'])}).")
        else:
            f.append("No store declined, so there is no 'greatest decline' to report.")
        if v["largest_pct_growth"]:
            g = v["largest_pct_growth"]
            f.append(f"Largest % growth: {g['store']} ({pct(g['change_pct'])}).")
    elif t == "get_monthly_revenue_share":
        top = sorted(v["by_month"], key=lambda x: -(x["revenue"] or 0))[:3]
        f.append("Highest months: " + "; ".join(f"{m['month']} {money(m['revenue'])} ({m['share_pct']:.2f}%)" for m in top) + ".")
        low = sorted(v["by_month"], key=lambda x: (x["revenue"] or 0))[0]
        f.append(f"Lowest month: {low['month']} {money(low['revenue'])} ({low['share_pct']:.2f}%). Total in scope: {money(v['total_revenue'])}.")
    elif t == "get_category_performance":
        if v.get("fastest_growing"):
            f.append(f"Fastest growth ({v['categories'][0].get('first_year')} to {v['categories'][0].get('last_year')}): "
                     f"**{v['fastest_growing']}**; slowest: {v['slowest_growing']}.")
        for c in v["categories"]:
            extra = (f", {pct(c['change_pct_first_to_last'])} from {c['first_year']} to {c['last_year']}"
                     if c.get("change_pct_first_to_last") is not None else "")
            f.append(f"{c['category']}: {money(c['revenue'])} ({c['share_pct']:.2f}%{extra}).")
    elif t == "get_satisfaction_vs_revenue":
        r = v["pearson_r_satisfaction_revenue"]
        f.append(f"Correlation between satisfaction and same-year store revenue: r = **{r}** "
                 f"across {v['store_years_used']} store-years ({v['store_years_missing_satisfaction']} without a score)."
                 if r is not None else "Not enough survey data in scope to compute a correlation.")
        if v["per_store"]:
            hi, lo = v["per_store"][0], v["per_store"][-1]
            f.append(f"Highest average satisfaction: {hi['store']} ({hi['avg_satisfaction']}); lowest: {lo['store']} ({lo['avg_satisfaction']}).")
    elif t == "get_data_quality_report":
        flagged = [i for i in v["issues"] if i["count"]]
        f.append(f"{len(flagged)} check(s) flagged:" if flagged else "No data-quality checks were flagged.")
        for i in flagged:
            f.append(f"{i['table']} - {i['check']}: {i['count']}" + (f" ({i['detail']})" if i["detail"] else ""))
    elif t == "get_data_coverage":
        f.append("The data contains revenue and survey scores only. It does NOT contain: " + ", ".join(v["NOT_available"]) + ".")
    return f


def _interpretation(plan_tools: list[str], q: str) -> tuple[str, str]:
    ql = q.lower()
    if "get_data_coverage" in plan_tools:
        return ("Revenue alone cannot establish profitability or whether a store should close; a falling revenue "
                "line could still be profitable (or a rising one unprofitable).",
                "To decide, management would need store-level operating costs, cost of goods, lease terms, staffing, "
                "and customer behaviour. **No recommendation is supported by this data alone.**")
    if "get_satisfaction_vs_revenue" in plan_tools:
        causal = re.search(r"cause|because|driv|effect|impact|lead to|result in", ql)
        return (("This is an association, not evidence of cause. " if causal else "") +
                "A positive r means higher-satisfaction store-years tended to have somewhat higher revenue; it does not "
                "show that raising satisfaction would raise revenue. Store size, market and location are not controlled for, "
                "and lost customers do not answer surveys.",
                "A controlled analysis (e.g. regression with market size and store type) or an experiment would be needed "
                "before acting on this.")
    if "get_store_trend" in plan_tools:
        return ("Store revenue trends describe what happened, not why.",
                "Investigate the declining stores' local markets, staffing and costs before drawing conclusions.")
    if "get_data_quality_report" in plan_tools:
        return ("Flagged items are potential problems, not confirmed errors.", "Review flagged rows with the data owner.")
    return ("These figures are calculated directly from the currently loaded data.",
            "No recommendation is supported by revenue figures alone; use the dashboard to drill into the details.")


def answer_rules(q: str, model, sidebar_filters: dict | None, use_sidebar: bool) -> Turn:
    turn = Turn(question=q, mode="Rules-based")
    plan = route_rules(q, model)
    if not plan:
        turn.answer = ("**Unsupported question.** I could not match this to one of my analytical functions, so I will "
                       "not guess.\n\n" + CAPABILITIES)
        return turn
    if use_sidebar:
        plan = _fill_from_sidebar(plan, sidebar_filters)
    results = [dispatch(model, t, a, turn.calls) for t, a in plan]
    main = next((r for r in results if r.get("tool") != "get_data_coverage"), results[0])
    findings = [x for r in results for x in _findings_for(r)]
    caveats = list(dict.fromkeys(c for r in results for c in r.get("caveats", [])))
    interp, nxt = _interpretation([t for t, _ in plan], q)
    if all(r.get("error") for r in results):
        interp = "Nothing was calculated, so there is nothing to interpret."
        nxt = "Rephrase the question using one of the valid values listed above."
    turn.answer = (f"**{scope_text(main.get('scope'), use_sidebar)}**\n\n"
                   "**Findings** (from the tool results)\n" + "\n".join(f"- {x}" for x in findings) +
                   f"\n\n**Interpretation**\n{interp}\n\n**Next steps**\n{nxt}" +
                   ("\n\n**Caveats**\n" + "\n".join(f"- {c}" for c in caveats) if caveats else ""))
    return turn


# --------------------------------------------------------------- Gemini router
SYSTEM_PROMPT = """You are the analytical assistant inside the E-Presso business-intelligence app.
Rules you must follow:
1. Answer ONLY by calling the provided functions. Never use outside knowledge or memorised E-Presso figures.
2. Every number you state must appear in a function result. Do not compute new numbers yourself except simple
   differences already shown. If a function returns an "error", explain it plainly.
3. Start the answer with one line "Scope: ..." describing the filters actually used (from the function result's
   "scope"). {scope_rule}
4. Then use exactly these headings: **Findings** (facts from function results), **Interpretation** (clearly
   labelled as interpretation), **Next steps** (or say "No recommendation is supported by this data").
5. Revenue is not profit. The data has no costs, expenses, rent or staffing. For any question about profit,
   closing/opening stores, ROI or costs, call get_data_coverage and explain what additional data is needed.
6. Correlation is not causation. For satisfaction questions call get_satisfaction_vs_revenue and say so.
7. Mention relevant caveats from the results (missing data, excluded rows).
8. If the question is not about E-Presso data, say what you can answer instead. Be concise."""


def _gemini_tools(model) -> list:
    av = A.allowed_values(model.sales)
    enums = {"channel": av["channel"], "store": av["store"], "category": av["category"]}
    decls = []
    for name, spec in TOOLS.items():
        props = {}
        for p in spec["params"]:
            if PARAM_TYPES[p] == "INTEGER":
                props[p] = {"type": "INTEGER", "description": f"Calendar year. Available: {av['year']}"}
            else:
                props[p] = {"type": "STRING", "enum": enums[p], "description": f"One of the {p} values in the data."}
        decl = {"name": name, "description": spec["description"]}
        if props:
            decl["parameters"] = {"type": "OBJECT", "properties": props}
        decls.append(decl)
    return [{"functionDeclarations": decls}]


class LLMUnavailable(RuntimeError):
    pass


def _post(url, payload, api_key, timeout=40):
    import requests  # imported lazily so tests run without network packages
    try:
        r = requests.post(url, json=payload, timeout=timeout,
                          headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise LLMUnavailable(f"Could not reach the Gemini API ({type(e).__name__}).") from e
    if r.status_code == 429:
        raise LLMUnavailable("The Gemini free-tier quota or rate limit has been reached.")
    if r.status_code == 404:
        raise FileNotFoundError(r.text[:200])
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = r.text[:200]
        raise LLMUnavailable(f"Gemini API error {r.status_code}: {msg[:200]}")
    return r.json()


def answer_gemini(q, model, api_key, model_names, sidebar_filters, use_sidebar) -> Turn:
    turn = Turn(question=q, mode="Gemini (LLM)")
    scope_rule = ("The user chose to apply the dashboard filters: pass these values as function parameters unless "
                  f"the question names different ones: {json.dumps(sidebar_filters)}." if use_sidebar and sidebar_filters
                  else "Use the full dataset unless the question names a year, channel, store or category.")
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT.format(scope_rule=scope_rule)}]},
        "contents": [{"role": "user", "parts": [{"text": q}]}],
        "tools": _gemini_tools(model),
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "generationConfig": {"temperature": 0},
    }
    last_err = None
    for mname in model_names:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mname}:generateContent"
        try:
            contents = list(payload["contents"])
            for _ in range(MAX_TOOL_CALLS):
                data = _post(url, {**payload, "contents": contents}, api_key)
                cand = (data.get("candidates") or [{}])[0]
                content = cand.get("content") or {}
                parts = content.get("parts") or []
                calls = [p["functionCall"] for p in parts if "functionCall" in p]
                if not calls:
                    turn.answer = "".join(p.get("text", "") for p in parts).strip()
                    if not turn.answer:
                        raise LLMUnavailable(f"Gemini returned no answer (finish reason: {cand.get('finishReason')}).")
                    turn.mode = f"Gemini (LLM: {mname})"
                    return turn
                contents.append(content)  # keep the model turn unchanged (includes any thought signatures)
                responses = []
                for c in calls:
                    res = dispatch(model, c.get("name", ""), c.get("args") or {}, turn.calls)
                    responses.append({"functionResponse": {"name": c.get("name", ""),
                                                           "response": json.loads(json.dumps(res, default=str))}})
                contents.append({"role": "user", "parts": responses})
            raise LLMUnavailable("The model kept calling tools without answering.")
        except FileNotFoundError as e:  # model name not available for this key: try the next one
            last_err = e
            continue
    raise LLMUnavailable(f"No configured Gemini model is available ({last_err}).")


# ------------------------------------------------------------ number checking
_NUM = re.compile(r"(?<![\w.])\$?\s?(-?\d[\d,]*(?:\.\d+)?)\s?(%|percent|million|m\b|k\b|thousand)?", re.I)


def _flatten_numbers(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_numbers(v, out)
            if isinstance(k, (int, float)) or (isinstance(k, str) and k.isdigit()):
                out.append(float(k))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten_numbers(v, out)
    elif isinstance(obj, str):
        for m in re.findall(r"-?\d[\d,]*\.?\d*", obj):
            try:
                out.append(float(m.replace(",", "")))
            except ValueError:
                pass


def unverified_numbers(answer: str, calls: list, question: str = "") -> list[str]:
    """Numbers in the answer that do not match any number in the tool results (within rounding)."""
    known: list[float] = []
    for c in calls:
        _flatten_numbers(c["result"], known)
        _flatten_numbers(c["args"], known)
    _flatten_numbers(question, known)
    known_abs = [abs(k) for k in known]
    flagged = []
    for m in _NUM.finditer(answer):
        raw, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        try:
            x = abs(float(raw))
        except ValueError:
            continue
        if x <= 31 and not unit:  # small counts, days, list numbering
            continue
        mult = 1e6 if unit in ("million", "m") else 1e3 if unit in ("k", "thousand") else 1
        val = x * mult
        tol = max(0.006 * val, 0.06 if unit in ("%", "percent") else 1.0)
        if mult > 1:
            tol = max(tol, 0.051 * mult)
        if not any(abs(val - k) <= tol for k in known_abs):
            flagged.append(m.group(0).strip())
    return list(dict.fromkeys(flagged))


# ------------------------------------------------------------------ entrypoint
def ask(q: str, model, *, api_key: str | None, model_names: list[str], sidebar_filters: dict | None,
        use_sidebar: bool) -> Turn:
    """Answer one question: Gemini if a key is configured and working, otherwise the rules-based router."""
    if api_key:
        try:
            turn = answer_gemini(q, model, api_key, model_names, sidebar_filters, use_sidebar)
            turn.unverified_numbers = unverified_numbers(turn.answer, turn.calls, q)
            if not turn.calls:
                turn.notice = "The model answered without calling any analytical function, so no figures are verified."
            return turn
        except LLMUnavailable as e:
            turn = answer_rules(q, model, sidebar_filters, use_sidebar)
            turn.notice = f"Language model unavailable - {e} Switched to the rules-based assistant for this answer."
            return turn
    return answer_rules(q, model, sidebar_filters, use_sidebar)
