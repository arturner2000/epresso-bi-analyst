# Reflection

**AI use.** I worked alone, with Claude (Anthropic) as my development partner. It wrote most of the code
(the Access reader, the analytics functions, the Streamlit app and the tests) and drafted the documentation,
including a first version of this reflection. I directed the work, made the design calls below, deployed the
app, and checked every number against Power BI and my own Looker Studio report.

**Biggest challenge: reading the Access file.** I work on a Mac, and Streamlit Cloud runs on Linux. Neither
can run Access or Power BI Desktop, and the usual Python readers would not install. So I rebuilt the Power BI
assignment in Looker Studio and had the AI write a small read-only .accdb parser. I trusted it only after it
matched three independent references: a separate prototype reader (25,200 rows), the walkthrough's Power BI
numbers ($42,174,440 total; Nov/Dec 12.71% and 25.61%) and my Looker report.

**How I found problems.** I logged rows and revenue before and after every join, tested on a tiny table I could
check by hand, and ran the $1,000 test on the live app (total → $42,175,440, Chicago 2029 → $180,130, no code
changes). Testing exposed a crash on an unknown Store ID and a router bug that dropped the year from "Chicago
revenue in 2029". Each was fixed, retested and given a regression test.

**Where the AI struggled.** It guessed the file's byte layout wrong at first, which broke the $1,000-edit tool.
Its first outlier rule flagged 2,327 normal December rows. One router fix made "What's the weather in Denver?"
return Denver revenue. Gemini also had problems on the live app. Its first answer failed with a 503
"high demand" error, because the code gave up instead of trying a backup model. After the fix, the answers
were correct, but slow, and in one case muddled: it called the "Interest" correlation "interest
satisfaction". Every number still traced back to a tool result, which is why I kept the tool-call log and the
number checker.

**Decisions that needed my judgment.** I joined Sales directly to Stores, so a missing survey row can't hide
revenue. I summed sales to store-year before comparing it with satisfaction. I labelled stores "City (ID)"
because there are two Orlando stores. And I chose what the assistant must refuse to answer: profitability,
causation and store closures.

**Would I trust it?** I would trust it for revenue facts. Every figure is reproducible and has been checked
against two BI tools and independent code. I would not trust it for decisions like closing Chicago. There is
no cost, lease or staffing data, the survey misses customers who left, and a correlation of 0.235 is not a
cause. Real use would need cost data, logins, automatic tests on every change, and human review of the
assistant's answers.
