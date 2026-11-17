# LSEG Workspace connector

Install the `lseg` extra in a dedicated environment. The connector opens
`desktop.workspace` through the official Python LSEG Data Library. Open
Workspace locally and sign in before you call `analyze`. Each user supplies
their own entitlement. For site-specific application configuration, use the
[official desktop connection guide](https://developers.lseg.com/en/article-catalog/article/troubleshooting-workspace-session-connections--part-2--verifying).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[lseg]"
.\.venv\Scripts\python.exe -m equity_workbench analyze US46625H1005
```

Use a ticker, ISIN or an exchange-qualified primary RIC. An ISIN is checked
against the returned security. Ticker resolution uses LSEG symbology. Supply the
primary RIC if a ticker is ambiguous or to specify the listing explicitly.
`search <company>` is a discovery command. The analysis itself takes a ticker,
ISIN or primary RIC. [LSEG symbology documentation](https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/tutorials/content-tutorials/symbology)

The connector selects the request set from the returned sector and reporting
model. It uses fiscal dates for financial statements and estimates, major
quote currency for forecasts, and a separate timestamp for the information
cutoff. It reconciles market cap and quote currencies before normalization.
For example, a Workspace GBp close is divided by 100 for a GBP analysis.
Historic fiscal data can include revisions. The live command uses data at
collection time.

Each run archives `workspace_snapshot.json` with request parameters and field
names. It writes `valuation/report.html`, the financial calculations,
forecast CSV and an audit including the source hash. `--drafts` adds notes
under `social/`. A failed run writes `report.html` and `status.json` with
the issue. `--from-snapshot` replays data locally.

The normal share route values the issuer and attributes value to the selected
primary class. For multiple classes, the attribution assumes their observed
relative shares of company market cap. Different economic rights need separate
analysis when that proportionality cannot be justified. Cross-currency
capitalization mismatches and insufficient current data block calculation.

The connector ships with no account configuration. Logs, rights-controlled
data, snapshots and generated reports remain local. GitHub Actions runs
fictional tests and builds the source archive. Review your Workspace
agreement before sharing underlying or derived market data.
[LSEG Data Library usage and limitations](https://developers.lseg.com/en/article-catalog/article/the-data-library-for-python-maximum-usage-reference-guide)
