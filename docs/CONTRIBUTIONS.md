# Contribution statement

**This is an individual project.** Alessandro (Rhett) Turner completed it alone, with no teammate, so every commit
in this repository is his.

| Who | Contribution |
|---|---|
| **Rhett Turner** (sole author) | Planned the approach. Collected the three course files from Canvas. Built the Looker Studio version of the Power BI assignment, which supplies the reference values. Created the GitHub repo and deployed the app on Streamlit Community Cloud. Configured secrets. Reviewed every calculation against the walkthrough and Looker. Ran the live $1,000 test and the assistant tests. Wrote the reflection. All commits. |
| **Claude (Anthropic), AI assistant** | Wrote most of the code: the Access reader, analytics functions, Streamlit app and tests. Drafted the validation and test documents. Found and fixed bugs during testing. Every AI-generated output was checked against independent results (see `VALIDATION.md`). |

AI use is also disclosed in the README and the reflection.

## Defense prep: questions I should be able to answer

1. What is the grain of Sales and Survey? Why is Sales summed to store-year before it's compared with satisfaction?
2. How do you know the joins didn't duplicate revenue? (Merge log: 25,200 rows and $42,174,440, before and after.)
3. How does the app read the .accdb? (`epresso/accdb_reader.py`: it reads the table-definition pages, then decodes each data page's rows. It's read-only.)
4. Why is website growth 121.6% when the walkthrough says "about 118%"? (The walkthrough rounded $3.2M and $7.0M before dividing.)
5. Walk through the $1,000 test. Which numbers changed, and which didn't?
6. What happens when a user asks the assistant a question? (Router → `dispatch()` → function → tool-contract result → answer + log.)
7. What can't the assistant do, and why? (No eval/exec, no new data, no profit claims, no causal claims.)
8. What happens if the Gemini quota runs out? (Visible notice, then a rules-based answer from the same functions.)
9. Why are stores labelled "Orlando (SH01)" and products grouped by ID?
10. Would you trust it for a store-closure decision? (No: there's no cost or lease data. See the reflection.)
