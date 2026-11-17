"""Static, escaped review reports. Rendering never changes valuation results."""

import html
import json
from pathlib import Path
from urllib.parse import urlparse

from . import __version__


def esc(value):
    return html.escape(str(value), quote=True)


def number(value, digits=2):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.{digits}f}"
    return "Unavailable"


def source_link(source):
    title = esc(source.get("title", source.get("id", "Source")))
    url = source.get("url", "")
    try:
        parsed = urlparse(url) if isinstance(url, str) else None
    except ValueError:
        parsed = None
    if parsed and parsed.scheme == "https" and parsed.netloc and not parsed.username:
        return f'<a href="{esc(url)}" rel="noopener noreferrer">{title}</a>'
    return title


CSS = """
:root{color-scheme:light;--ink:#172b39;--muted:#506674;--line:#dce5e8;--accent:#007e80}
*{box-sizing:border-box}body{margin:0;background:#f2f6f7;color:var(--ink);font:16px/1.6 system-ui,sans-serif}
main{max-width:1160px;margin:auto;padding:42px 30px 70px}h1{font-size:clamp(2rem,5vw,3.4rem);line-height:1.08;letter-spacing:-.04em;margin:12px 0 18px}
h2{font-size:1.35rem;margin:0 0 15px}h3{font-size:1.08rem}p{max-width:84ch}a{color:#00676a;overflow-wrap:anywhere}
.eyebrow{font-size:.78rem;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:750}
.muted{color:var(--muted)}.badge{display:inline-block;padding:7px 13px;border-radius:5px;background:#fff0ce;color:#6b4700;font-size:.85rem;font-weight:750}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:28px 0}.card,section{background:white;border:1px solid var(--line);border-radius:12px;padding:24px}
.card .label{font-size:.82rem;color:var(--muted)}.card strong{display:block;font-size:2rem;margin-top:7px;font-variant-numeric:tabular-nums}
section{margin-top:18px}.note{border-left:4px solid var(--accent);padding:10px 16px;background:#eef7f7}
.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{text-align:left;border-bottom:1px solid var(--line);padding:12px 10px;vertical-align:top}th{font-size:.76rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:#f7fafb}
.numeric{text-align:right;font-variant-numeric:tabular-nums}ul{padding-left:22px}.error{color:#9d2323}.warning{color:#785516}
pre{white-space:pre-wrap;word-break:break-word;background:#f5f8fa;padding:18px;border-radius:8px;font-size:.78rem;max-height:650px;overflow:auto}
details{margin-top:14px}summary{cursor:pointer;font-weight:650}.footer{font-size:.8rem;color:var(--muted);margin-top:25px}
@media(max-width:700px){main{padding:25px 14px}.cards{grid-template-columns:1fr}.card,section{padding:18px}h1{font-size:2.2rem}}
@media print{body{background:white}main{padding:0}.card,section{break-inside:avoid}details{display:block}pre{max-height:none}}
"""


def shell(title, body):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


def workspace_summary(research):
    ttm = research["ttm"]
    body = (
        f'<section><h2>Workspace research data</h2><p>RIC {esc(research["ric"])} · ISIN {esc(research["isin"])} · '
        f'{esc(research["industry"])}. Reference close {esc(research["market_day"])}. '
        'This is a current information snapshot. Financial history can include provider restatements.</p>'
        f'<p>Last four quarters: revenue {number(ttm["revenue"])} · EBIT {number(ttm["ebit"])} · '
        f'operating cash flow {number(ttm["cfo"])} · PPE cash expenditure {number(ttm["cash_capex"])}. '
        f'Reported less provider-normalized net income {number(research["normalized_income_gap"])}. '
        'That earnings difference is a diagnostic and does not establish a cash adjustment.</p>'
        '<div class="table-wrap"><table><thead><tr><th>Fiscal period</th><th>Type</th><th>Revenue</th>'
        '<th>EBIT</th><th>Operating margin</th><th>Operating cash flow</th><th>PPE cash expenditure</th>'
        '</tr></thead><tbody>'
    )
    for label, rows in (("LSEG standardized", research["annual"]), ("LSEG consensus", research["consensus"])):
        for row in rows:
            body += (f'<tr><td>{esc(row["period_end"])}</td><td>{label}</td><td>{number(row["revenue"])}</td>'
                     f'<td>{number(row["ebit"])}</td><td>{row["ebit"]/row["revenue"]:.1%}</td>'
                     f'<td>{number(row.get("cfo"))}</td><td>{number(row.get("cash_capex"))}</td></tr>')
    return (body + '</tbody></table></div><p>The forecast uses an aggregate net-investment proxy from operating '
            'cash conversion, cash capex and growth in gross finance-lease assets. The proxy can include one-off '
            'cash effects and lease disposals or reclassifications. Book capital and quarterly dilution are proxies.</p></section>')


def write_blocked_workspace_report(path, identifier, snapshot, reason):
    requests = (snapshot or {}).get("requests", {})
    rows = requests.get("identity", {}).get("rows", [])
    row = rows[0] if rows else {}
    name = row.get("TR.COMMONNAME", identifier)
    body = (f'<h1>{esc(name)}</h1><span class="badge">Valuation unavailable</span>'
            f'<section><h2>Input or coverage issue</h2><p>{esc(reason)}</p>'
            f'<p>RIC/identifier {esc(row.get("Instrument", identifier))} · ISIN {esc(row.get("TR.ISIN", "Unavailable"))}</p>')
    if row.get("TR.PRICECLOSE") is not None:
        body += (f'<p>Provider close {number(row["TR.PRICECLOSE"])} {esc(row.get("TR.PRICECLOSE.CURRENCY", ""))} · '
                 f'{esc(str(row.get("TR.PRICECLOSE.DATE", ""))[:10])}</p>')
    Path(path).write_text(shell(name, body + '</section>'), encoding="utf-8")


def write_direct_equity_report(path, case, result, audit, plan):
    company = case["company"]
    base = result["scenarios"]["base"]
    currency = company["currency"]
    body = (f'<div class="eyebrow">TickerFoundry · {esc(result["method_label"])}</div>'
            f'<h1>{esc(company["name"])}</h1><span class="badge">Private research draft</span>'
            f'<p>{esc(company["ticker"])} · {esc(company["isin"])} · {esc(plan["industry"])} · '
            f'Information cutoff {esc(case["valuation_at"])}.</p>'
            f'<p>Market close {esc(case["market_date"])} at <strong>{number(case["market_price"])} {esc(currency)}</strong>. '
            f'StarMine cost of equity {result["cost_of_equity"]:.2%} on {esc(plan["cost_date"])}.</p>'
            '<section><h2>Value by scenario</h2><table><thead><tr><th>Scenario</th><th>Value per share</th>'
            '<th>Terminal growth</th></tr></thead><tbody>')
    for name, row in result["scenarios"].items():
        body += f'<tr><td>{esc(name.title())}</td><td>{number(row["value_per_share"])}</td><td>{row["terminal_growth"]:.2%}</td></tr>'
    body += '</tbody></table>'
    if result["equity_method"] == "residual_income":
        book = plan["quarterly"][-1]
        body += (f'<p>Common book value {number(book["book"])} million {esc(currency)} at {esc(book["period_end"])}. '
                 f'Market P/B {case["market_cap"]/book["book"]:.2f}×. Model terminal ROE {base["terminal_roe"]:.2%}. The market quote implies '
                 f'{base["implied_terminal_roe"]:.2%} terminal ROE when the explicit forecast and discount rate are held fixed.</p>'
                 '<p>Common book equity is the last reported amount. Future net repurchases, OCI, regulatory capital '
                 'and solvency governance remain issuer-specific. The model reconciles residual income and the equivalent dividend value.</p>')
    else:
        implied = base["implied_terminal_dividend_growth"]
        body += (f'<p>Market forward P/FFO {base["forward_price_to_ffo"]:.2f}×. The implied terminal dividend growth is '
                 f'{f"{implied:.2%}" if implied is not None else "unavailable"} at the base discount rate.</p>'
                 '<p>Forecast dividends use forward DPS and DPS/FFO. Property-level NAV, maintenance capex and lease-level risk '
                 'require further evidence.</p>')
    body += ('</section><section><h2>Consensus and sensitivity</h2>'
             '<table><thead><tr><th>Fiscal year</th><th>Income (millions) or FFO per share</th><th>DPS</th></tr></thead><tbody>')
    for row in plan["estimates"]:
        body += f'<tr><td>{esc(row["period_end"])}</td><td>{number(row["profit_or_ffo"])}</td><td>{number(row["dps"])}</td></tr>'
    body += '</tbody></table><ul>'
    for cell in result["sensitivities"]:
        body += f'<li>Cost of equity {cell["cost_of_equity"]:.2%} · {number(cell["value_per_share"])} {esc(currency)}</li>'
    body += '</ul></section><section><h2>Base forecast and sources</h2><div class="table-wrap"><table><thead><tr>'
    columns = list(base["forecast_rows"][0])
    body += "".join(f'<th>{esc(key.replace("_", " "))}</th>' for key in columns)
    body += '</tr></thead><tbody>'
    for row in base["forecast_rows"]:
        body += ("<tr>" + "".join(f'<td>{esc(row[key]) if key == "period_end" else number(row[key])}</td>'
                                  for key in columns) + "</tr>")
    body += '</tbody></table></div><ul>'
    body += "".join(f'<li>{source_link(item)}</li>' for item in case["sources"])
    body += f'</ul><p>Input SHA-256 {esc(audit.get("input_sha256"))}</p></section>'
    Path(path).write_text(shell(company["name"], body), encoding="utf-8")


def write_report(path, case, result, audit, reviews=None, plan=None):
    if result and result.get("equity_method"):
        write_direct_equity_report(path, case, result, audit, plan)
        return
    company = case.get("company") if isinstance(case.get("company"), dict) else {}
    name = company.get("name", "Company")
    currency = company.get("currency", "")
    synthetic = case.get("synthetic") is True
    badge = "FICTIONAL TEST DATA · NOT AN INVESTMENT ANALYSIS" if synthetic else "DRAFT · SOURCE AND HUMAN REVIEW REQUIRED"
    if result is None:
        badge = "BLOCKED · INPUT ERRORS"
    identity = " · ".join(str(company[key]) for key in ("ticker", "exchange") if company.get(key))
    body = f'<div class="eyebrow">Equity Research Workbench {__version__}</div><h1>{esc(name)}</h1><span class="badge">{badge}</span>'
    body += f'<p class="muted">{esc(identity)} · {esc(case.get("valuation_at", case.get("valuation_date", "Unknown")))} · {esc(currency)}. Monetary statements and share counts are in millions.</p>'
    body += '<p class="note">This report preserves the supplied assumptions and the deterministic calculation. Passing input checks does not verify the facts, prove the assumptions, or authorize publication.</p>'
    if result is not None:
        body += '<div class="cards">'
        for label, value in (("DCF value / share", result.get("value_per_share")),
                             ("Supplied price / share", result.get("market_price")),
                             ("Enterprise value (millions)", result.get("enterprise_value"))):
            body += f'<div class="card"><span class="label">{esc(label)}</span><strong>{number(value)}</strong><span class="muted">{esc(currency)}</span></div>'
        body += '</div>'
        share = result.get("terminal_value_share")
        if isinstance(share, (int, float)):
            body += f'<p>Present value of the terminal component / enterprise value: <strong>{share:.1%}</strong>. This ratio can exceed 100% when explicit-period cash flows are negative; it is not a confidence level.</p>'
        if "scenarios" in result:
            body += '<section><h2>Operating scenarios</h2><div class="table-wrap"><table><thead><tr>'
            body += '<th>Case</th><th>Value / share</th><th>Versus close</th><th>Terminal EBIT margin</th><th>Economic drivers</th></tr></thead><tbody>'
            for key, scenario in result["scenarios"].items():
                body += (f'<tr><td>{esc(key.title())}</td><td>{number(scenario["value_per_share"])}</td>'
                         f'<td>{scenario["upside_fraction"]:+.1%}</td><td>{scenario["terminal"]["operating_margin"]:.1%}</td>'
                         f'<td>{esc(scenario["rationale"])}</td></tr>')
            capital = result["capital_cost"]
            body += f'</tbody></table></div><p>WACC {capital["wacc"]:.2%} · '
            if capital.get("method") == "lseg_starmine":
                body += (f'StarMine {esc(capital["as_of"])} · equity cost {capital["cost_of_equity"]:.2%} · '
                         f'debt cost component {capital["debt_cost_component"]:.2%} · ')
            else:
                body += (f'nominal risk-free rate {capital["risk_free_rate"]:.2%} · equity premium '
                         f'{capital["equity_risk_premium"]:.2%} · pretax debt cost {capital["pre_tax_cost_of_debt"]:.2%} · ')
            body += (f'beta {capital["beta"]:.3f} · debt weight {capital["debt_weight"]:.2%}.</p>'
                     f'<p>{esc(capital["rationale"])}</p>')
            alternate = result.get("beta_cross_check")
            if alternate:
                body += (f'<p><strong>Beta sensitivity.</strong> Beta {alternate["beta"]:.3f} gives WACC '
                         f'{alternate["wacc"]:.2%} and {number(alternate["value_per_share"])} {esc(currency)} per share '
                         'with the same operating forecast.</p>')
            body += '</section>'
        if plan and plan.get("editorial"):
            context = plan["editorial"]
            body += '<section><h2>Business and evidence</h2>'
            for label in ("business", "evidence", "assumptions", "risk", "falsifier"):
                if context.get(label):
                    body += f'<p>{esc(context[label])}</p>'
            body += '</section>'
        if plan and plan.get("research"):
            body += workspace_summary(plan["research"])
    body += '<section><h2>Review status</h2><ul>'
    checks = audit.get("checks", [])
    for item in checks:
        body += f'<li class="{esc(item.get("severity", ""))}"><strong>{esc(item.get("code", "Check"))}:</strong> {esc(item.get("message", ""))}</li>'
    if not checks:
        body += '<li>Structural checks passed. Evidence support, assumptions and publication rights still require review.</li>'
    body += '</ul><p>Publication ready: <strong>No</strong>. This starter never grants publication approval.</p></section>'
    assumptions = case.get("assumptions") if isinstance(case.get("assumptions"), dict) else {}
    body += '<section><h2>Assumptions</h2><div class="table-wrap"><table><thead><tr><th>Assumption</th><th>Supplied value</th></tr></thead><tbody>'
    for key, value in assumptions.items():
        rendered = f"{value:.2%}" if isinstance(value, (int, float)) and key != "rationale" else esc(value)
        body += f'<tr><td>{esc(key.replace("_", " "))}</td><td>{rendered}</td></tr>'
    body += '</tbody></table></div></section>'
    if result is not None:
        rows = result.get("forecast_rows", [])
        body += '<section><h2>Cash-flow calculation</h2><p>Net reinvestment must include all operating investment after the relevant depreciation and amortization offsets. It is deducted once.</p>'
        if rows:
            columns = [("period_end", "Period end"), ("revenue", "Revenue"), ("ebit", "EBIT"), ("nopat", "NOPAT"), ("net_reinvestment", "Net investment"), ("fcff", "FCFF"), ("pv_fcff", "Present value")]
            body += '<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th>{label}</th>' for _, label in columns) + '</tr></thead><tbody>'
            for row in rows:
                body += '<tr>' + ''.join(f'<td>{esc(row.get(key, "")) if key == "period_end" else number(row.get(key))}</td>' for key, _ in columns) + '</tr>'
            body += '</tbody></table></div>'
        body += '</section><section><h2>Conditional reverse DCF</h2><p>The reverse calculation varies the terminal operating margin while explicit cash flows and other inputs remain fixed. It does not identify a unique market expectation or explain a share-price change.</p>'
        reverse = result["reverse_dcf"]
        if reverse["status"] == "solved":
            body += (f'<p>Closing price {number(reverse["target_price"])} implies a terminal EBIT margin of '
                     f'<strong>{reverse["terminal_operating_margin"]:.1%}</strong> under the base assumptions.</p>')
        else:
            body += f'<p>{esc(reverse["reason"])}</p>'
        body += '</section><section><h2>WACC and terminal growth</h2><div class="table-wrap"><table><thead><tr><th>WACC</th><th>Growth</th><th>DCF / share</th></tr></thead><tbody>'
        for cell in result["sensitivities"]:
            body += f'<tr><td>{cell["wacc"]:.2%}</td><td>{cell["terminal_growth"]:.2%}</td><td>{number(cell["value_per_share"])}</td></tr>'
        body += '</tbody></table></div></section>'
        body += '<section><h2>Model detail and sensitivities</h2><p>The machine-readable result retains the forecast, valuation bridge and sensitivity calculations.</p>'
        body += f'<details><summary>Inspect the calculated output</summary><pre>{esc(json.dumps(result, indent=2, allow_nan=False))}</pre></details></section>'
    body += '<section><h2>Source register</h2><p>These metadata are supplied by the operator. A source link alone does not prove that it supports a financial input or permits reuse.</p><div class="table-wrap"><table><thead><tr><th>ID / source</th><th>Published</th><th>Retrieved</th><th>Reuse / cloud processing</th></tr></thead><tbody>'
    sources = case.get("sources") if isinstance(case.get("sources"), list) else []
    for src in sources:
        if not isinstance(src, dict):
            continue
        body += f'<tr><td>{esc(src.get("id", ""))}<br>{source_link(src)}</td><td>{esc(src.get("published_at", ""))}</td><td>{esc(src.get("retrieved_at", ""))}</td><td>{esc(src.get("redistribution", "unknown"))} / {esc(src.get("cloud_processing", "unknown"))}</td></tr>'
    body += '</tbody></table></div></section>'
    if result is not None:
        body += '<section><h2>Enterprise-to-equity inputs</h2><div class="table-wrap"><table><thead><tr><th>Input</th><th>Value</th><th>Date</th><th>Source / definition</th></tr></thead><tbody>'
        for name, fact in case["facts"].items():
            body += (f'<tr><td>{esc(name.replace("_", " "))}</td><td>{number(fact["value"])}</td>'
                     f'<td>{esc(fact["period_end"])}</td><td>{esc(fact["source_id"])} · {esc(fact["basis"])}</td></tr>')
        body += '</tbody></table></div></section>'
        body += '<section><h2>Limits of this run</h2><ul>'
        body += ''.join(f'<li>{esc(item)}</li>' for item in result.get("limitations", []))
        body += '</ul></section>'
    if reviews is not None:
        body += '<section><h2>Astra reviewer findings</h2><p>These are model-generated review drafts. They do not alter the valuation or replace source verification.</p>'
        body += f'<pre>{esc(json.dumps(reviews, indent=2, allow_nan=False))}</pre></section>'
    body += f'<p class="footer">Input SHA-256: {esc(audit.get("input_sha256", "Unavailable"))}<br>Generated: {esc(audit.get("generated_at", "Unknown"))}. Research software; no trading or publishing action has been performed.</p>'
    Path(path).write_text(shell(f"{name} — valuation review", body), encoding="utf-8")


def write_research_report(path, dossier):
    body = '<div class="eyebrow">Equity Research Workbench / public-source research</div><h1>Research dossier</h1><span class="badge">DRAFT · NOT A VERIFIED VALUATION</span>'
    body += '<p>Astra generated this research draft using web search. Validate issuer identity, sources, publication dates and every material claim before constructing the financial model.</p>'
    body += f'<section><h2>Findings and missing inputs</h2><pre>{esc(json.dumps(dossier, indent=2, allow_nan=False))}</pre></section>'
    Path(path).write_text(shell("Company research dossier", body), encoding="utf-8")
