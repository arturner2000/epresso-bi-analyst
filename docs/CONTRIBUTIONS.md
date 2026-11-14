# Team contribution statement (fill in)

The Project Guide requires **commits from every team member**. Each of you should make real commits:
deploying, editing the README or docs, running the tests and recording the results, adding screenshots.

| Team member | Main responsibilities | Key calculation or design decision I can explain | Approximate commits |
|---|---|---|---|
| *Name 1* | e.g. data loading and validation, $1,000 test, deployment | e.g. why Sales joins directly to Stores, and the before/after merge checks | |
| *Name 2* | e.g. assistant testing, Gemini setup, reflection | e.g. how the dispatcher limits the model to named functions, and why profit questions are refused | |

## Defense prep: questions each of you should be able to answer

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
