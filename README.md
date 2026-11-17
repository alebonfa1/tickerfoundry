# TickerFoundry

Reproducible stock valuation from a ticker or ISIN. TickerFoundry downloads inputs through the user's own LSEG Workspace session and produces a local HTML report with valuation scenarios and an audit trail.

The analysis selects an enterprise DCF for operating businesses, a residual-income model for financial firms, or a dividend model with FFO coverage for equity REITs.

With Workspace signed in and the dependencies installed, run:

```powershell
python -m equity_workbench analyze US46625H1005
```
