# E-Presso BI Analyst

A hosted Streamlit business-intelligence app for the fictional E-Presso coffee-equipment company:
an interactive revenue dashboard, data-quality checks, and an analytical assistant that answers business
questions **only** by calling tested Python functions on the currently loaded data.

**Live app:** https://arturner2000-epresso-bi-analyst-streamlit-app-mlxnbs.streamlit.app/ · **Course:** Applied Data Science, AI Business Intelligence Challenge

---

## What it does

| Area | Details |
|---|---|
| **Data loading** | Reads the three original course files *in their original formats*, including the Access database (`.accdb`), with a built-in pure-Python reader (no Access, ODBC or mdbtools needed). Upload updated copies in the sidebar → everything recalculates, no code changes. Any file not uploaded falls back to the bundled original, and the app shows where every table came from. |
| **Dashboard** | KPIs (total, website, brick-and-mortar, latest-year growth); revenue by store type; revenue by year × channel; monthly pattern ($ or % of total); category trends; store change between any two years; market → city drill-down; satisfaction vs revenue scatter with trend line; store table. Sidebar filters (year, channel, store, category) are built from the loaded data and drive every chart, KPI and table. |
| **Data quality & model** | Table profiles, grain statements, relationship notes, before/after merge checks, 20+ data-quality rules, and a four-way reconciliation of the total. |
| **Analytical assistant** | Chat box → router → **dispatcher** → named analytical function → result → answer with *Scope / Findings / Interpretation / Next steps*. Tool-call log (function, arguments, raw JSON result) under every answer. Gemini function calling when an API key is configured; otherwise (or if the API fails / quota runs out) a clearly labelled rules-based router uses the same functions. 15-question session limit. Numbers in model answers are checked against tool results and anything unmatched is flagged. |

## Files

```
streamlit_app.py            UI only (layout, charts, chat)
epresso/accdb_reader.py     reads tables from .accdb files (read-only)
epresso/data_loader.py      file recognition, type cleaning, data model, merge checks, grain table
epresso/analytics.py        ALL calculations - the "tool contract" functions used by dashboard + assistant
epresso/agent.py            tool registry, dispatcher, rules router, Gemini router, number checker
analytics.py, agent.py      thin re-exports kept for the course template layout
data/                       original course files (default data)
tests/test_analytics.py     pytest suite on a tiny hand-calculable table + regression tests
validation/                 independent check, export of Access tables, $1,000 modified-data tool + file
docs/                       VALIDATION.md, AGENT_TESTS.md, REFLECTION.md, CONTRIBUTIONS.md
```

## Data model and grain

| Table | Source | One row = | Key | Revenue? |
|---|---|---|---|---|
| Sales | `.accdb` / Sales (25,200 rows) | monthly revenue for one store (or the website) × one product | Sales ID | **Yes** |
| Stores | `Support_EX_B_Stores.csv` (21) | one location (20 stores + website SH00) | ID | No |
| Products | `.accdb` / Products (20) | one product | Product ID | No |
| Categories | `.accdb` / Categories (5) | one category | Category ID | No |
| Survey | `.xlsx` / Survey Results (105) | one yearly survey result for one store | Survey ID = StoreYear | No |

* Sales joins **directly** to Stores (`Store ID = ID`), Products and Categories - all many-to-one, validated
  with `validate="m:1"`; rows and revenue are recorded before/after each merge and must not change.
* Survey is store-**year** grain while Sales is store-product-**month** grain, so Sales is summed to store-year
  *before* joining to the survey (1:1). Joining the raw tables would repeat each survey row 240 times.
* Two stores are in Orlando (SH01, SH08) and three products are called "Base Model" (P11, P15, P19), so stores
  are labelled *City (ID)* and products are grouped by ID.
* The website (SH00) has no satisfaction scores; survey analyses exclude it and say so.

## How to use

1. Open the app. It loads the original data automatically.
2. Use the sidebar filters; the caption under the title states the current scope.
3. To test updated data: sidebar → **Data source** → upload a modified `Support_EX_B_Sales.accdb`, `Stores.csv`
   or `Survey.xlsx` (or a table exported to `.csv`/`.xlsx` with the same column names). Remove the upload to
   return to the original data. Caching is keyed on the file *contents*, so new numbers appear immediately.
4. **Analytical assistant** tab: type a question or click an example. Toggle *Apply the dashboard filters* to
   answer for the filtered subset instead of the full dataset. Open *Tool-call log* to see the evidence.

## Run locally / deploy

```bash
pip install -r requirements.txt
python -m pytest -q                     # 17 tests
python validation/independent_check.py  # independent recomputation of the validation measures
streamlit run streamlit_app.py
```

Deploy on [share.streamlit.io](https://share.streamlit.io): *Create app* → this repo → main file `streamlit_app.py`.
For the language-model assistant add a secret in *App settings → Secrets*:
`GEMINI_API_KEY = "..."` (free key from Google AI Studio). Never commit keys; `.streamlit/secrets.toml` is git-ignored.

## Assistant boundaries

* The model (or the keyword router) can only **choose among the 10 named functions** in `epresso/agent.py`
  and supply parameters; enum parameters are limited to values that exist in the loaded data, and unknown values
  return an error result instead of a guess. No `eval`/`exec`, no model-written pandas/SQL, no pandas-agent
  libraries, and no function modifies data.
* Every answer states its scope, separates **Findings** (from tool results) from **Interpretation** and
  **Next steps**, and carries the tools' caveats (revenue ≠ profit, correlation ≠ causation, missing data).
* Profit, cost, closing-a-store or ROI questions trigger `get_data_coverage`, which lists what the data does not
  contain; the assistant then says no recommendation is supported.
* Mode is shown on every answer. Rules-based mode is a keyword router, **not** a language model.

## Limitations

* Revenue only - no costs, so no profitability. Survey scores exist only for physical stores and only from
  customers who still shop there. Correlations are associations.
* The Access reader supports the column types used by these tables (number, currency, date, text, yes/no);
  memo/attachment columns are ignored. A database saved with a password or as Access 97 is rejected with a message.
* The rules-based router understands a fixed set of question patterns; unsupported questions are refused with a
  list of what it can answer.
* Year-over-year growth compares calendar-year totals; it does not adjust for seasonality inside a year.

## AI use

Built with Claude (Anthropic) as the development partner: data investigation, the Access reader, analytics,
app, tests and documentation drafts. The team reviewed and tested every calculation (see `docs/`).
