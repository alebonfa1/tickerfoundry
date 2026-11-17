"""Local LinkedIn and Instagram drafts generated from replayed valuation inputs."""

from hashlib import sha256
import json

from . import INVESTMENT_DISCLAIMER
from .cli import fresh_output, load_json
from .model import SCENARIOS, evaluate_plan
from .validation import zoned_timestamp


def _with_hash(path, digest):
    if sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"{path.name} does not match the run audit")
    return load_json(path)


def direct_equity_copy(plan, result):
    base = result["scenarios"]["base"]
    first = plan["estimates"][0]
    if result["equity_method"] == "residual_income":
        method = "Reddito residuo"
        evidence = f"LSEG stima un utile di {first['profit_or_ffo']:,.0f} milioni nell’esercizio al {first['period_end']}."
        implied = f"A parità delle altre ipotesi, il prezzo implica un ROE terminale di {base['implied_terminal_roe']:.1%}."
        risk = "Le stime dipendono dalla redditività del capitale, dai requisiti prudenziali e dalla politica di distribuzione."
        falsifier = "Confrontare utili, patrimonio comune e distribuzioni con le ipotesi del modello."
    else:
        method = "Dividendi attualizzati"
        evidence = f"Il multiplo corrente sui FFO attesi è {base['forward_price_to_ffo']:.1f} volte."
        implied = "Il multiplo usa i FFO per azione stimati da Workspace."
        risk = "Il valore dipende da copertura dei dividendi, investimenti immobiliari e costo del capitale."
        falsifier = "Monitorare FFO, dividendi e investimenti di mantenimento."
    return {
        "business": f"Gruppo settoriale Workspace: {plan['industry']}.", "evidence": evidence,
        "risk": risk, "falsifier": falsifier,
    }, method, implied, f"Costo del capitale proprio {base['cost_of_equity']:.2%}, crescita terminale {base['terminal_growth']:.1%}."


def write_drafts(run, destination):
    audit = load_json(run / "audit.json")
    case = load_json(run / "input_snapshot.json")
    if case.get("synthetic") is not False or audit.get("status") != "needs_review":
        raise ValueError("Drafts require a completed, real-company research run")
    if zoned_timestamp(case.get("valuation_at")) is None:
        raise ValueError("Drafts require an offset-aware market cutoff")
    case_bytes = json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if sha256(case_bytes).hexdigest() != audit.get("input_sha256"):
        raise ValueError("Case snapshot does not match the run audit")
    plan = _with_hash(run / "driver_plan.json", audit.get("plan_sha256"))
    result = _with_hash(run / "calculations.json", audit.get("calculations_sha256"))
    replayed_case, replayed_result = evaluate_plan(case, plan)
    if replayed_case != case or replayed_result != result:
        raise ValueError("Current model did not reproduce the archived calculation")
    company = case["company"]
    name = company["name"]
    currency = company["currency"]
    day = case["valuation_date"]
    price = f"{result['market_price']:.2f} {currency}"
    names = {"downside": "Stress", "base": "Base", "upside": "Favorevole"}
    values = " · ".join(f"{names[key]} {result['scenarios'][key]['value_per_share']:.2f}" for key in SCENARIOS)
    if result.get("equity_method"):
        context, method, implied, assumptions = direct_equity_copy(plan, result)
        quote_day = case["market_date"]
        valuation = f"{method} per azione ({currency}) — {values}."
    else:
        context = plan["editorial"]
        for key in ("business", "evidence", "assumptions", "risk", "falsifier"):
            if not isinstance(context.get(key), str) or not context[key].strip():
                raise ValueError(f"Editorial field {key} is required")
        quote_day = case["facts"]["market_price"]["period_end"]
        valuation = f"DCF per azione ({currency}) — {values}. WACC base {result['capital_cost']['wacc']:.2%}."
        alternate = result.get("beta_cross_check")
        if alternate:
            valuation += (f" Con beta alternativo {alternate['beta']:.2f} e stessi flussi, "
                          f"base {alternate['value_per_share']:.2f} {currency} (WACC {alternate['wacc']:.2%}).")
        reverse = result["reverse_dcf"]
        implied = (
            f"Con le altre ipotesi base fisse, il prezzo richiede un margine EBIT terminale del "
            f"{reverse['terminal_operating_margin']:.1%}."
            if reverse["status"] == "solved" else
            "Il prezzo è fuori dall’intervallo riproducibile variando solo il margine EBIT terminale."
        )
        annual = plan["scenarios"]["base"]["annual"][0]
        terminal = result["scenarios"]["base"]["assumptions"]
        assumptions = (
            f'{context["assumptions"]} Crescita ricavi nel primo anno completo '
            f'{annual["revenue_growth"]:.1%}, margine EBIT terminale {terminal["terminal_operating_margin"]:.1%}, '
            f'crescita terminale {terminal["terminal_growth"]:.1%}.'
        )
    source_map = {item["id"]: item for item in case["sources"]}
    source_ids = context.get("source_ids", list(source_map)[:2])
    if not isinstance(source_ids, list) or not source_ids or any(sid not in source_map for sid in source_ids):
        raise ValueError("Every editorial source ID must match a source in the case")
    primary = [source_map[sid] for sid in source_ids]
    sources = "\n".join(f"- {item['title']} — {item['url']}" for item in primary)
    sources += "\nLe fonti di mercato e le ipotesi sono nel dossier completo."
    release = ("Bozza interna. Prima della diffusione verificare attribuzione, "
               "interessi e conflitti, diritti dei dati, fonti e collegamento al dossier.")
    output = fresh_output(destination)
    linkedin = [
        INVESTMENT_DISCLAIMER, release, f"{name} ({company['ticker']}) | Analisi {day} | Chiusura {quote_day} {price}",
        context["business"], context["evidence"], assumptions, valuation, implied,
        context["risk"], context["falsifier"], f"Fonti\n{sources}",
    ]
    slides = [
        ("Domanda di ricerca", f"{name} | Analisi {day} | Chiusura {quote_day} {price}. Quale redditività richiede questa quotazione?"),
        ("Business", context["business"]),
        ("Dati", context["evidence"]),
        ("Ipotesi", assumptions),
        ("Scenari", valuation),
        ("Mercato implicito", implied),
        ("Cosa monitorare", f"{context['risk']} {context['falsifier']}"),
        ("Fonti e disclosure", release),
    ]
    instagram = "\n\n".join(f"## {i}. {title}\n\n{copy}\n\n{INVESTMENT_DISCLAIMER}" for i, (title, copy) in enumerate(slides, 1))
    caption = f"{name} | {day}. {valuation} {implied}\n\n{INVESTMENT_DISCLAIMER}\n\n{release}\n\nFonti\n{sources}"
    (output / "linkedin.md").write_text("\n\n".join(linkedin) + "\n", encoding="utf-8")
    (output / "instagram.md").write_text(f"{instagram}\n\n## Didascalia\n\n{caption}\n", encoding="utf-8")
