# Reflection

**AI tools used.** I used Claude (Anthropic) for almost all of the hands-on work. Working in my browser and its own
workspace, it read the data, wrote all the code (Access reader, analytics, Streamlit app, assistant, tests), built
my Looker Studio version of the Power BI assignment, deployed the app, ran the validation and agent tests, and
drafted the documentation, including this reflection. Google Gemini is the language model inside the app's
assistant. My role was directing: I chose to do the Power BI assignment first in Looker Studio, kept my friend's
report untouched, worked solo, set up the accounts and the Gemini key, pushed for improvements against the rubric,
and questioned claims that weren't accurate. That included an earlier draft of this reflection, which credited me
with decisions Claude had made.

**Biggest challenge: reading the Access file.** I work on a Mac, and Streamlit Cloud runs on Linux. Neither can run
Access or Power BI Desktop. Claude wrote a small read-only .accdb parser and only trusted it after it matched a
separate prototype reader (25,200 rows), the walkthrough's Power BI numbers ($42,174,440) and my Looker report.

**How problems were found.** Claude logged rows and revenue before and after every join, tested on a tiny table
with known answers, and ran the $1,000 test on the live app (total → $42,175,440, Chicago 2029 → $180,130, no code
changes). Testing caught a crash on an unknown Store ID and a router bug that dropped the year from "Chicago revenue
in 2029". Each was fixed and retested.

**What the AI did well and where it struggled.** It was fast and thorough, and its own tests caught most of its
bugs. But it guessed the file's byte layout wrong at first. Its first outlier rule flagged 2,327 normal December
rows, and one fix made "weather in Denver" return Denver revenue. On the live app, Gemini first failed with a 503
error until backup models were added, and it later mislabelled one figure. Claude also overstated my role in its
first draft of this reflection.

**Decisions that needed judgment.** Claude made the main design choices, and I had to understand them to explain the
app. Sales joins directly to Stores, so a missing survey row can't hide revenue. Sales is summed to store-year
before it's compared with satisfaction, because the survey is yearly. Stores are labelled "City (ID)" because there
are two Orlando stores. The assistant refuses questions about profit, causes and store closures, because the data
can't answer them.

**Would I trust it?** For revenue facts, yes: they match two BI tools and independent code. For decisions like
closing Chicago, no. There's no cost or lease data, the survey misses customers who left, and a correlation of
0.235 is not a cause. Real use would need cost data, logins, automatic tests and human review of the assistant's
answers. I would also need to understand the code myself much better than I do now.
