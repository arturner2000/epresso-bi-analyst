# Team reflection (DRAFT – edit so it is true for your team, 300–500 words)

**AI tools used.** We used Claude (Anthropic) as our development partner. It investigated the files and wrote
the Access reader, analytics functions, app, tests and documentation drafts. *(Add any other tools you used, such as ChatGPT or Gemini, and what you used them for.)*

**Biggest challenge: getting the data out of the Access database.** Our laptops are Macs. Power BI Desktop
and Microsoft Access don't run on macOS, and Streamlit Community Cloud runs on Linux with no Access driver.
The usual tools (`mdbtools`, `access-parser`) could not be installed, so we had the AI write a small
read-only .accdb parser. To check it, we compared it against a separate
prototype reader: both returned the same 25,200 Sales rows. Its output also matches Power BI (Microsoft's own driver) exactly: $42,174,440 total; November and
December shares 12.71% and 25.61%.

**How we diagnosed problems.** We recorded rows and revenue before and after every join, and wrote tests on
a tiny table whose answers we could work out by hand. Edge-case uploads exposed a crash on an unknown Store ID;
agent testing showed the router dropping the year from "Chicago revenue in 2029". We fixed, retested and added
regression tests.

**Where the AI helped and where it struggled.** It was fast at boilerplate, charts, and drafting rules and
tests. It struggled in three places:
- **Byte layout.** Its first assumption about the file's column storage was wrong: all columns are stored as
  variable-length. This broke the first version of the $1,000-edit tool.
- **Over-broad keyword rules.** One fix made "What's the weather in Denver?" return Denver store revenue.
- **Outlier check.** Its first outlier rule (IQR) flagged 2,327 normal December rows in this skewed,
  seasonal data, and it attached an explanation it had not verified. We replaced the rule with one that
  compares each month to the same store and product's median.

**What needed our judgment.**
- **Join path.** We joined Sales directly to Stores rather than going through the survey table, as Power BI
  does. Sales already has the key, and this way a missing survey row can't hide revenue.
- **Grain.** We summed Sales to store-year before comparing it with satisfaction.
- **Name collisions.** We labelled stores by City (ID) because there are two Orlando stores, and grouped
  products by ID because three products are called "Base Model".
- **Refusals.** We decided what the assistant must refuse to conclude: profitability, causation, closures.

**Would we trust it for real decisions?** We would trust it for the *revenue facts*. Every figure is
reproducible, reconciled four ways, and checked against an independent method. We would not trust it for
*decisions*. There is no cost, lease or staffing data, the survey misses lost customers, and correlations are not
causes. Real use would need:
- cost and profit data
- authentication and access control
- tests running automatically on every commit
- logging and human review of assistant answers
- clear rules for which questions the assistant may answer at all
