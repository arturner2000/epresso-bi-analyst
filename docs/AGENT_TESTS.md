# Analytical assistant tests

**What was built:** Option A (a Gemini function-calling agent) **plus** the Option B rules-based router.
The rules-based router answers whenever no API key is set, or when the API fails or the quota runs out.
The results below were recorded in **rules-based mode** on the original data, unless a row says otherwise.

**Live-app evidence (14 Nov 2026, rules-based mode, original data unless noted).** Each screenshot shows the answer and its expanded tool-call log:
[Test 1](t1_website_2028.jpg) · [Test 2](t2_store_decline.jpg) · [Test 3](t3_most_profitable.jpg) · [Test 4](t4_satisfaction.jpg) · Test 5 [before](t5_before_assistant.jpg) / [after](t5_after_sidebar_assistant.jpg).
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
| G | First live Gemini run (14 Nov 2026) | Gemini returned HTTP 503 "high demand"; the app went straight to rules-based mode (safe and clearly labelled, but no AI answer) — [screenshot](g_fallback_503.jpg) | 503/429 errors and timeouts were treated as final; the backup models were never tried | A busy model is now retried once, then the next model is tried (`gemini-2.5-flash` → `gemini-flash-latest` → `gemini-2.5-flash-lite` → `gemini-flash-lite-latest` → `gemini-2.0-flash`), with a 75 s total budget before the rules fallback. New tests: `test_busy_model_is_retried_then_next_model_used` and the all-busy and timeout fallbacks. Retest: all five tests answered by Gemini (see below). |

## Controls verified

* **Only named tools run.** Calling the dispatcher with `exec` returns "Unknown tool 'exec'. Allowed: …". Unknown parameters are dropped and reported.
* **Unknown values are rejected, not guessed.** For example: "Year(s) [2031] not in the data. Available years: [2025 … 2029]"; "'Orlando' matches more than one store".
* **Number checker** (`unverified_numbers`). In a simulated Gemini reply, an invented "$9,999" is flagged; every number in the rules-based answers matches a tool result. Covered by `test_gemini_loop_uses_only_named_tools`.
* **API failure.** A simulated quota error switches to rules-based mode with a visible notice (`test_gemini_failure_falls_back_to_rules`).
* **Session limit.** After 15 questions the chat box is disabled and an explanation is shown.

## Evidence that answers come from the app's calculations

[g6_raw_tool_result.jpg](g6_raw_tool_result.jpg) shows a Gemini answer, "Chicago in 2029 was **$179,130**", with its
tool-call log fully expanded. The raw result from `get_revenue_summary` reads `"total_revenue": 179130`,
`"rows_used": 240` and scope `{"year":[2029], "store":"Chicago (SH11)"}`, so the number in the answer is the
number the function returned. Further evidence:

* **Independent agreement.** Every tested figure matches `validation/independent_check.py`, which shares no code with the app, and the Power BI walkthrough.
* **Data-sensitivity.** After the $1,000 upload, the same question returned $180,130. A fabricated answer could not track a one-row change.
* **Controls.** The model can only call the 10 named functions; it has no code execution or raw data. A number checker flags any figure that isn't in a tool result (tested with an invented "$9,999").

## Live Gemini run (14 Nov 2026, after fix G)

`GEMINI_API_KEY` was set in Streamlit Secrets, and the assistant banner shows **"Language-model agent (Gemini function calling)"** ([screenshot](g0_gemini_mode.jpg)).
`gemini-2.5-flash` was overloaded, so the fallback chain answered with **`gemini-flash-lite-latest`**. The answer header names the model that was used.

| Test | Function Gemini chose (args) | Gemini's answer | Matches rules-based baseline / expected? | Screenshot |
|---|---|---|---|---|
| 1. Website revenue 2028 | `get_revenue_summary` `{"channel":"Website","year":2028}` | $6,339,640 from 240 rows | ✅ Same number | [g1](g1_website_2028.jpg) |
| 2. Greatest % decline | `get_store_trend` `{}` | Chicago (SH11), −66.81% ($539,740 → $179,130) | ✅ Same store and figures | [g2](g2_store_decline.jpg) |
| 3. Most profitable store | `get_data_coverage` `{}` | Refused to name a store. Explained that the data has no costs, rent, staffing or margins, and listed the data needed | ✅ Correct refusal. Gemini made 1 call; the rules router makes 2 (it also shows revenue trends) | [g3](g3_most_profitable.jpg) |
| 4. Satisfaction → revenue? | `get_satisfaction_vs_revenue` `{}` | r = 0.235; "Correlation is not causation"; no control for market size or store type; lost customers aren't surveyed | ✅ Same r and caveats. **Finding:** it labelled the tool's `pearson_r_interest_revenue` (0.125) as "interest satisfaction correlation". The number is real and traceable, but the wording is muddled, and it listed every store's figures (verbose) | [g4](g4_satisfaction.jpg) |
| 5. Chicago 2029, before/after the $1,000 upload | `get_revenue_summary` `{"year":2029,"store":"Chicago (SH11)"}` | Before **$179,130** (header "original course data"); after **$180,130** (header "total $42,175,440 · UPLOADED data") | ✅ Updated without code changes | [before](g5_before_chicago.jpg) / [after](g5_after_chicago.jpg) |

**Comparison with the rules-based mode.** Both modes produced identical numbers because both call the same tested functions; Gemini only changes which function is chosen and how the answer is worded. Gemini handled the questions without keyword matching and wrote more natural interpretations, but was slower (≈15–40 s per answer on the free tier during high demand vs. instant) and occasionally verbose or loosely worded (Test 4). The number checker, tool-call log and rules fallback mean a wrong or unavailable model cannot silently change a figure.
