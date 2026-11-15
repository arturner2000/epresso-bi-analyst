# Contribution statement

**This is an individual project.** Alessandro (Rhett) Turner is the only student on it, and every commit is from
his account. Most of the hands-on work was done by an AI assistant, as described below.

| Who | Contribution |
|---|---|
| **Rhett Turner** (sole student) | Chose the approach: the Power BI assignment first, rebuilt in Looker Studio, then the app. Made the scope decisions: kept a friend's report untouched, worked solo. Created the Google, GitHub, Streamlit and Gemini accounts, accepted their terms and set the Gemini key. Uploaded files to GitHub. Directed the work against the rubric and reviewed the results. Caught that an earlier draft of the reflection overstated his role. |
| **Claude (Anthropic), AI assistant** | Did most of the hands-on work. Read the data. Wrote all the code: Access reader, analytics, Streamlit app, assistant, tests. Built the Looker Studio report in the browser. Deployed and fixed the app. Ran the validation, the $1,000 test and the agent tests on the live app. Drafted all the documentation, including the reflection. |

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
