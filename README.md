# TickerFoundry

Turn a stock ticker or ISIN into a reproducible valuation report. TickerFoundry
downloads the required inputs from your signed-in LSEG Workspace desktop,
chooses a valuation method, and produces a local HTML report with financial
scenarios and the data needed to rerun it.

## Quick start

Download or clone this repository and open a terminal in it. Start **LSEG
Workspace** on the same computer and sign in with your own licensed account.
Set up the Python environment once. Python 3.11 or later is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[lseg]"
```

On macOS or Linux, use `.venv/bin/python` where the examples use the Windows
virtual environment path, with an available provider session.

Run one command with a ticker, ISIN or primary exchange-qualified RIC:

```powershell
.\.venv\Scripts\python.exe -m equity_workbench analyze MSFT
.\.venv\Scripts\python.exe -m equity_workbench analyze US46625H1005
```

Use `--drafts` to add private LinkedIn and Instagram drafts. Each successful
run prints the report path. The default output directory is `runs/lseg/`.
The same command produces a coverage report when an input check blocks a
defensible value.

## Use with Codex

Open this repository in Codex with the model you prefer, including GPT-6.1 Sol.
Ask, for example, **“Analyze ISIN US46625H1005 with TickerFoundry using my
local Workspace session.”** The instructions in [AGENTS.md](AGENTS.md) direct
the agent to run the program and read the saved results. The deterministic
valuation runs in Python and does not require an AI API.

## Valuation coverage

| Company economics | Valuation method | Key inputs |
|---|---|---|
| Operating businesses | Enterprise FCFF discounted at WACC | Standardized statements, EBIT and revenue consensus, financial claims and reinvestment |
| Banks, insurers and other financial firms | Common-equity residual income discounted at the cost of equity | Common book value, earnings and dividend consensus, implied terminal ROE |
| Equity REITs | Dividend discount with forward FFO coverage and P/FFO | Dividend and per-share FFO consensus, cost of equity |

Current coverage depends on the provider fields, current data rights and
model fit. Missing or inconsistent evidence, complex claims, distress and
special situations can require analyst inputs. See [methodology](docs/METHODOLOGY.md)
and [Workspace guide](docs/LSEG_WORKSPACE.md). This release uses LSEG Workspace
for live downloads and supports provider-neutral normalized cases for manual DCF.

## Reproduce and contribute

`workspace_snapshot.json` stores the exact field requests and normalized
provider responses. Replay it on the same model version:

```powershell
.\.venv\Scripts\python.exe -m equity_workbench analyze --from-snapshot "runs/lseg/<run>/workspace_snapshot.json"
```

Offline tests and the fictional demo need no provider session:

```powershell
python -m unittest discover -s tests -v
python -m equity_workbench demo --out runs/demo
```

The public repository contains original source and fictional tests. Each user
uses their own local provider session. Account settings, credentials,
downloaded data, reports and licensed reference material belong outside Git.
See [data rights](docs/DATA_RIGHTS.md) and [validation](docs/VALIDATION.md).
