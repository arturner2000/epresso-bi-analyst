# Validation

**Reference ("Power BI result") column:** figures from the course Power BI walkthrough
(*Using Power BI – Assignment Walkthrough*), which were produced by Power BI from the same three files.
➜ *Team: if your own Power BI / Looker Studio report shows more precise values (hover tooltips), paste them
in and attach screenshots.*

**App result:** the deployed app on the original data (Overview, Trends and Stores tabs; same numbers from
`epresso/analytics.py`).

## 1. Power BI vs. app

| Metric | Power BI result (walkthrough) | App result | Match? / Explanation |
|---|---|---|---|
| Total revenue (five years, 2025–2029) | "about $42 million" | **$42,174,440** | ✅ Match (Power BI figure is rounded to $M). |
| Website revenue | "about $27 million" | **$27,218,880** (64.54%) | ✅ Match. |
| Brick-and-mortar revenue | "$15 million" | **$14,955,560** (35.46%) | ✅ Match; 27.22 + 14.96 = 42.17 M. |
| Revenue by year | $7.2M (2025) → $9.2M (2029), "almost 28%" | 2025 **$7,181,750** · 2026 **$8,016,950** · 2027 **$8,824,720** · 2028 **$8,969,470** · 2029 **$9,181,550**; +27.85% | ✅ Match. |
| Revenue by year – by channel | B&M $4.0M → $2.2M "45% decline"; Website $3.2M → $7.0M "about 118%" | B&M **$4,021,520 → $2,178,300 (−45.83%)**; Website **$3,160,230 → $7,003,250 (+121.61%)** | ✅ Dollar values match. ⚠️ The walkthrough's 118% is computed from the *rounded* $3.2M and $7.0M (7.0/3.2 − 1 = 118.75%). From exact values the growth is 121.61%. The app is right; the difference is rounding in the text, not a data or model difference. |
| Monthly revenue pattern | Nov **12.71%**, Dec **25.61%** of total; Nov + Dec "$16.2 million" | Nov **12.71%** ($5,361,150), Dec **25.61%** ($10,800,990); Nov + Dec $16,162,140 | ✅ Exact match to two decimals. Denominator in both: the five-year grand total (Power BI "Percent of grand total"). Lowest month: Feb 3.83%. |
| Additional measure: Chicago vs Phoenix store trend | Chicago $0.54M → $0.18M "67% decrease"; Phoenix $0.53M → $0.47M "about 11%" | Chicago **$539,740 → $179,130 (−66.81%)**; Phoenix **$529,260 → $467,010 (−11.76%)** | ✅ Dollars match. Phoenix "about 11%" again comes from the rounded values (0.47/0.53 − 1 = −11.3%); exact is −11.76%. |

**Model difference worth noting.** The walkthrough relates *Stores → Survey Results → Sales* (Stores.ID →
Survey.Store ID, Survey.Survey ID → Sales.StoreYear), so store attributes reach Sales *through the survey
table*. That works only because every StoreYear (including the website's SH00_25…29) has a survey row. If an
updated survey file dropped a row, Power BI would put those sales under a blank store type. The app joins Sales
directly to Stores on `Store ID` (Sales already has the key), so revenue by store type does not depend on the
survey file. Both give identical results on the original data; the app's design is more robust to the
instructor's modified files.

## 2. Independent check (reproducible)

`python validation/independent_check.py`

* **What:** total revenue, website vs brick-and-mortar, revenue by year × channel, monthly share, and
  Chicago's 2025→2029 change.
* **How:** it does **not** import the app's code. It reads CSV exports of the Access tables produced by a
  *separate* prototype reader (`validation/export_accdb_tables.py`, written independently of
  `epresso/accdb_reader.py`), maps StoreType with a plain dictionary lookup instead of a merge, and uses simple
  pandas group-bys. The two readers' outputs were compared row by row (identical, 25,200 rows).
* **Result:** Rows 25,200; total **42,174,440.00**; Website **27,218,880.00**; Brick & Mortar
  **14,955,560.00**; yearly and monthly values identical to the table above; Chicago 539,740 → 179,130 (−66.81%).
* Exact agreement with Power BI's 12.71% / 25.61% (which Power BI computed with Microsoft's own Access driver)
  is strong evidence that the custom reader decodes every Revenue value correctly.
* The app also shows a live four-way reconciliation (raw Sales sum, `get_revenue_summary`, sum of channels, sum of
  months) on the *Data quality & model* tab.

## 3. Merge checks (original data)

| Merge | Rows before | Rows after | Revenue before | Revenue after | Explanation |
|---|---|---|---|---|---|
| Sales → Stores on Store ID = ID (m:1, left) | 25,200 | 25,200 | 42,174,440 | 42,174,440 | Stores.ID is unique; every Store ID matched. |
| + Products on Product ID (m:1, left) | 25,200 | 25,200 | 42,174,440 | 42,174,440 | Product ID unique. |
| + Categories on Category ID (m:1, left) | 25,200 | 25,200 | 42,174,440 | 42,174,440 | Category ID unique. |
| Sales summed to StoreYear → Survey (1:1) | 105 store-years | 105 | 42,174,440 | 42,174,440 | Aggregated first, so no repetition. |

## 4. $1,000 modified-data test

Access is not available on macOS, so the copy was edited with `validation/make_modified_accdb.py`, which changes
only the 8 bytes of one Revenue value (byte comparison: exactly 2 bytes differ) and refuses to overwrite the
original. The modified file is saved as `validation/modified_data/Support_EX_B_Sales.accdb`.

| Item | Entry |
|---|---|
| Table and row identifier | Sales, **Sales ID S1120291201** |
| Date / store / channel of the row | 2029-12-31 · Chicago (SH11) · Brick & Mortar · Beans / French Roast (P01) |
| Original value | **$1,200.00** |
| Modified value | **$2,200.00** (+$1,000.00) |
| Expected total revenue after change (predicted before upload) | $42,174,440 + $1,000 = **$42,175,440** |
| Actual total revenue after change | **$42,175,440** ✅ |
| Chart that should change, and what you saw | *Revenue by year*: 2029 total $9,181,550 → **$9,182,550** and Brick & Mortar 2029 $2,178,300 → **$2,179,300**; *Monthly pattern*: December $10,800,990 → **$10,801,990**; *Store change*: Chicago 2029 $179,130 → **$180,130**, change −66.81% → **−66.63%**. All observed as predicted. |
| Filter combinations checked (changed / unchanged) | **Changed (+1,000):** Brick & Mortar ($14,956,560); Year 2029; Store Chicago (SH11) + 2029 ($180,130); Category Beans ($5,673,720). **Unchanged:** Website ($27,218,880); Year 2028 ($8,969,470); Phoenix (SH09) ($2,527,100); Beans + 2029 + Website ($894,580); Dec share stays 25.61% (rounding). |
| Code changes required? | **None.** File uploaded through the sidebar; no restart. Sidebar shows "Sales: UPLOADED: Support_EX_B_Sales.accdb". |
| Assistant before/after | "How much revenue did Chicago generate in 2029?" → before **$179,130**, after **$180,130** (tool `get_revenue_summary`, args `{"year":[2029],"store":"Chicago"}`). |
| Original data restored? | Yes - removing the upload returns the app to the bundled original ($42,174,440). The original file was never modified. |

### Live-app evidence (deployed app, 14 Nov 2026)

The test was repeated on the hosted app by uploading `validation/modified_data/Support_EX_B_Sales.accdb` in the sidebar, with no code changes or restart.

| Step | Observed on the live app | Screenshot |
|---|---|---|
| Before (original data) | Assistant: Chicago 2029 = **$179,130**, header "original course data" | [t5_before_assistant.jpg](t5_before_assistant.jpg) |
| After upload: KPIs | Total **$42,175,440**, Brick & Mortar **$14,956,560**, Website unchanged $27,218,880. Banner: "Using uploaded data … Sales ← Support_EX_B_Sales.accdb" | [t5_after_overview.jpg](t5_after_overview.jpg) |
| After upload: Stores chart | Chicago 2025→2029 change **−66.6%** (was −66.8%) | [t5_after_stores.jpg](t5_after_stores.jpg) |
| After upload: assistant + sidebar | Chicago 2029 = **$180,130**; tool `get_revenue_summary` `{"year":[2029],"store":"Chicago"}`; sidebar lists the uploaded file | [t5_after_sidebar_assistant.jpg](t5_after_sidebar_assistant.jpg) |
| Restored | Upload removed → total back to **$42,174,440** | [t5_restored_overview.jpg](t5_restored_overview.jpg) |
