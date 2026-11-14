# Analytical assistant tests

**What was built:** Option A (a Gemini function-calling agent) **plus** the Option B rules-based router.
The rules-based router answers whenever no API key is set, or when the API fails or the quota runs out.
The results below were recorded in **rules-based mode** on the original data, unless a row says otherwise.

**Live-app evidence (14 Nov 2026, rules-based mode, original data unless noted).** Each screenshot shows the answer and its expanded tool-call log:
[Test 1](screenshots/t1_website_2028.jpg) · [Test 2](screenshots/t2_store_decline.jpg) · [Test 3](screenshots/t3_most_profitable.jpg) · [Test 4](screenshots/t4_satisfaction.jpg) · Test 5 [before](screenshots/t5_before_assistant.jpg) / [after](screenshots/t5_after_sidebar_assistant.jpg).
All five gave the expected result on the deployed app. If a `GEMINI_API_KEY` is added later, the same questions can be rerun in Gemini mode and compared with this baseline.

Independent verification uses `validation/independent_check.py` (separate code) and the Power BI walkthrough.

| Test | Question asked | Function(s) used | Expected result / behavior | Actual result | Pass / Fail | Revision made |
|---|---|---|---|---|---|---|
| 1. Numerical calculation | How much revenue did the website generate in 2028? | `get_revenue_summary` `{"year":[2028],"channel":"Website"}` | Website 2028 revenue = **$6,339,640**, from the independent check's year × channel pivot | **$6,339,640** from 240 rows; scope line "year = 2028; channel = Website"; caveat that revenue ≠ profit | Pass | – |
| 2. Numerical comparison | Which store experienced the greatest percentage revenue decline? | `get_store_trend` `{}` (defaults 2025 → 2029) | Chicago (SH11), −66.81% ($539,740 → $179,130), matching Power BI's "67% decrease". If nothing declined, say so rather than naming a store. | **Chicago (SH11) −66.8%**; "20 of 21 locations had lower revenue". All 20 physical stores declined; only the website grew (+121.6%). No-decline case, with the Website filter applied: "No store declined, so there is no 'greatest decline' to report." | Pass | – |
| 3. Missing information | Which E-Presso store is the most profitable? | `get_data_coverage`, `get_store_trend` | Refuse to name a "most profitable" store. Explain that revenue is not profit, list the data that would be needed, and offer revenue evidence only. | Lists what the data does NOT contain (costs, margin, rent, staffing…). Shows revenue trends labelled as revenue. Ends: "**No recommendation is supported by this data alone.**" | Pass | – |
| 4. Analytical judgment | Does higher customer satisfaction cause higher revenue? | `get_satisfaction_vs_revenue` | Report the association (r), n and the missing survey rows. State plainly that correlation is not causation, and name confounders and survivorship bias. | r = **0.235** across 100 store-years (5 website store-years have no score). "This is an association, not evidence of cause…". Mentions store size, market, location, and that lost customers don't answer surveys. Suggests a controlled analysis. | Pass | – |
| 5. Updated data | How much revenue did Chicago generate in 2029? Asked before and after uploading the $1,000-modified `.accdb`. | `get_revenue_summary` `{"year":[2029],"store":"Chicago"}` | Before **$179,130**, after **$180,130**. The answer header shows which data was used. | Before **$179,130** (original data). After **$180,130**, with the header "data at answer time: 25,200 rows · total $42,175,440 · UPLOADED data". | Pass (after fix A) | **Fix A**, below |
| Extra: fix and retest | (same question as Test 5) | First run: `get_revenue_by_year` `{"store":"Chicago"}` | One number for 2029 only | **Fail on the first run.** The router dropped the year: a "store named" rule ran *before* the "revenue" rule, so it returned all five years. | Fail → Pass | Reordered the rules so the revenue rule runs first. The store-only rule now runs only for performance questions ("how did X do?"). Retest: correct tool, `year: [2029]`, $179,130 / $180,130. Regression test added: `test_router_regressions`. |

## Other defects found and fixed during testing

| # | Found by | Symptom | Cause | Fix and retest |
|---|---|---|---|---|
| B | Asked "Which product category is growing fastest?" | Listed every category's growth but never answered "which" | `get_category_performance` returned no ranking | Added `fastest_growing` / `slowest_growing` to the result, and the answer now leads with it (Espresso Machines +32.0%; slowest Syrups +17.3%). |
| C | Edge-case upload: a Sales row with a Store ID missing from Stores | The app crashed: `TypeError: boolean value of NA is ambiguous` | The store-label code used `np.where` on a column with missing values | New `_store_label()` labels it "Unknown store (ID)". It shows up in the data-quality report and as an "Unknown store" channel. Regression test `test_sales_row_with_unknown_store_does_not_crash`. |
| D | Asked "How did Orlando do?" | Answered "Unsupported", although Orlando is a store | No rule handled a store name on its own | Added the store-performance rule. Because there are two Orlando stores, the assistant now asks for the store ID instead of guessing. Asking for "SH08" returns that store's yearly revenue. |
| E | Asked "What's the weather in Denver?" after fix D | Returned Denver store revenue | Fix D was too broad | That rule now requires performance words. Retest: correctly "Unsupported" with a list of capabilities. |
| F | Reviewed answer text | Negative money showed as "$-360,610" | Formatting | Now shows "−$360,610". |

## Controls verified

* **Only named tools run.** Calling the dispatcher with `exec` returns "Unknown tool 'exec'. Allowed: …". Unknown parameters are dropped and reported.
* **Unknown values are rejected, not guessed.** For example: "Year(s) [2031] not in the data. Available years: [2025 … 2029]"; "'Orlando' matches more than one store".
* **Number checker** (`unverified_numbers`). In a simulated Gemini reply, an invented "$9,999" is flagged; every number in the rules-based answers matches a tool result. Covered by `test_gemini_loop_uses_only_named_tools`.
* **API failure.** A simulated quota error switches to rules-based mode with a visible notice (`test_gemini_failure_falls_back_to_rules`).
* **Session limit.** After 15 questions the chat box is disabled and an explanation is shown.
