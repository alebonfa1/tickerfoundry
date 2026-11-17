"""Local command-line interface; network calls are explicit commands/options."""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from . import INVESTMENT_DISCLAIMER, __version__
from .reporting import write_report, write_research_report


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    def reject_constant(value):
        raise ValueError("JSON must not contain NaN or infinity")
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_no_duplicates, parse_constant=reject_constant)


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def code_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def fresh_output(path):
    folder = Path(path)
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Output directory is not empty; use a new directory to preserve previous runs")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def input_template(company, as_of, basis="enterprise"):
    valuation_date = date.fromisoformat(as_of)
    end_year = valuation_date.year if valuation_date.month != 12 or valuation_date.day != 31 else valuation_date.year + 1
    start = valuation_date + timedelta(days=1)
    forecasts = []
    for year in range(end_year, end_year + 6):
        end = date(year, 12, 31)
        forecasts.append({"period_start": start.isoformat(), "period_end": end.isoformat(),
                          "revenue": None, "operating_margin": None, "tax_rate": None,
                          "net_reinvestment": None, "rationale": ""})
        start = end + timedelta(days=1)
    fact_names = ("cash", "debt", "other_claims", "other_nonoperating_assets",
                  "valuation_shares", "shares_outstanding", "market_price")
    template = {
        "schema_version": "0.1",
        "company": {"name": company, "ticker": "", "exchange": "", "currency": "", "sector_model": "non_financial"},
        "valuation_date": as_of, "synthetic": False,
        "units": {"money": "millions", "shares": "millions", "price": "currency_per_share"},
        "sources": [],
        "facts": {key: {"value": None, "source_id": "", "period_end": "", "basis": ""} for key in fact_names},
        "assumptions": {"discount_convention": "end_period_actual_365", "wacc": None, "terminal_growth": None, "terminal_roic": None,
                        "terminal_operating_margin": None, "terminal_tax_rate": None, "rationale": ""},
        "forecasts": forecasts,
    }
    if basis == "common-equity":
        from .common_equity import CONVENTION, SCENARIOS
        from .validation import EQUITY_FACTS, EQUITY_SCHEMA
        template["schema_version"] = EQUITY_SCHEMA
        del template["company"]["sector_model"]
        del template["assumptions"]
        del template["forecasts"]
        template["discount_convention"] = CONVENTION
        template["facts"] = {key: template["facts"][key] for key in EQUITY_FACTS}
        template["scenarios"] = {
            name: {"cost_of_equity": None, "terminal_growth": None, "terminal_annual_cash_flow": None,
                   "source_ids": [], "rationale": "",
                   "forecasts": [{"period_start": row["period_start"], "period_end": row["period_end"],
                                  "net_cash_to_common": None, "source_ids": [], "rationale": ""}
                                 for row in forecasts]}
            for name in SCENARIOS
        }
    return template


def run_case(input_path, output_path, use_astra=False, model="gpt-6-astra", reasoning="high", plan_path=None):
    plan = load_json(plan_path) if plan_path is not None else None
    return run_prepared_case(load_json(input_path), output_path, use_astra, model, reasoning, plan)


def run_prepared_case(case, output_path, use_astra=False, model="gpt-6-astra", reasoning="high",
                      plan=None, evidence=None):
    from .core import evaluate_case
    from .validation import EQUITY_SCHEMA, validate_case

    if not isinstance(case, dict):
        raise ValueError("The case must be a JSON object")
    common_equity = case.get("schema_version") == EQUITY_SCHEMA
    if common_equity and (plan is not None or use_astra):
        raise ValueError("A common-equity case already contains its scenario forecasts. Run it with --input and --out.")
    result = None
    if plan is not None:
        from .model import evaluate_plan
        if use_astra:
            raise ValueError("Astra review accepts explicit cases. Run it separately on the materialized case.")
        case, result = evaluate_plan(case, plan)
    output = fresh_output(output_path)
    canonical = json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    issues = result["checks"] if result and result.get("equity_method") else validate_case(case)
    if common_equity and not any(item["severity"] == "error" for item in issues):
        from .common_equity import evaluate_common_equity
        try:
            result = evaluate_common_equity(case)
            issues = result["checks"]
        except (ValueError, ArithmeticError) as exc:
            issues.append({"severity": "error", "code": "calculation_range", "message": str(exc)})
    audit = {"software_version": __version__, "generated_at": datetime.now(timezone.utc).isoformat(),
             "input_sha256": hashlib.sha256(canonical).hexdigest(), "code_sha256": code_hash(),
             "status": "blocked" if any(i["severity"] == "error" for i in issues) else "needs_review",
             "publication_ready": False, "source_content_verified": False, "disclaimer": INVESTMENT_DISCLAIMER,
             "astra_requested": use_astra,
             "model_requested": model if use_astra else None,
             "reasoning_requested": reasoning if use_astra else None, "checks": issues}
    if evidence is not None:
        audit["evidence"] = evidence
    write_json(output / "input_snapshot.json", case)
    if plan is not None:
        write_json(output / "driver_plan.json", plan)
        audit["plan_sha256"] = hashlib.sha256((output / "driver_plan.json").read_bytes()).hexdigest()
    if audit["status"] == "blocked":
        write_json(output / "audit.json", audit)
        write_report(output / "report.html", case, None, audit)
        print(f"Input checks failed. Inspect {output / 'report.html'}")
        return 2
    if result is None:
        result = evaluate_case(case)
    audit["checks"] = result.get("checks", issues)
    if case.get("synthetic") is True:
        audit["status"] = "synthetic_demonstration"
    reviews = None
    if use_astra:
        from .astra import run_agent_review
        try:
            reviews = run_agent_review(case, result, model=model, reasoning_effort=reasoning)
            write_json(output / "agent_reviews.json", reviews)
            audit["astra_completed"] = True
        except (ValueError, RuntimeError) as exc:
            audit["astra_completed"] = False
            audit["checks"].append({"severity": "error", "code": "ASTRA_REVIEW_INCOMPLETE", "message": str(exc)})
            audit["status"] = "review_incomplete"
    write_json(output / "calculations.json", result)
    audit["calculations_sha256"] = hashlib.sha256((output / "calculations.json").read_bytes()).hexdigest()
    rows = result.get("forecast_rows", [])
    if rows:
        with (output / "forecast.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    write_report(output / "report.html", case, result, audit, reviews, plan)
    write_json(output / "audit.json", audit)
    print(f"Review report: {output / 'report.html'}")
    print("Status: " + audit["status"] + "; publication_ready=false")
    return 3 if audit["status"] == "review_incomplete" else 0


def analyze_workspace(ric, output, snapshot_path=None, drafts=False):
    from .lseg_analysis import materialize_workspace
    from .lseg_workspace import check_ric, fetch_snapshot

    if (ric is None) == (snapshot_path is None):
        raise ValueError("Supply one ticker, ISIN or primary RIC, or use --from-snapshot")
    snapshot = load_json(snapshot_path) if snapshot_path else None
    if snapshot is not None and not isinstance(snapshot, dict):
        raise ValueError("Workspace snapshot must be a JSON object")
    ric = check_ric(snapshot["ric"] if snapshot is not None else ric)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = fresh_output(output or Path("runs") / "lseg" / f"{ric}-{stamp}")
    snapshot_file = root / "workspace_snapshot.json"
    try:
        if snapshot is None:
            print(f"Downloading {ric} from LSEG Workspace ...", flush=True)
            snapshot = fetch_snapshot(ric)
        write_json(snapshot_file, snapshot)
        case, plan = materialize_workspace(snapshot)
        status = run_prepared_case(
            case, root / "valuation", plan=plan,
            evidence={"provider": "LSEG Workspace", "ric": snapshot["ric"], "snapshot_at": snapshot["snapshot_at"],
                      "sdk_version": snapshot["sdk_version"], "file": "../workspace_snapshot.json",
                      "sha256": hashlib.sha256(snapshot_file.read_bytes()).hexdigest()},
        )
    except (OSError, ValueError, RuntimeError, KeyError, AttributeError, TypeError) as exc:
        write_json(root / "status.json", {"status": "blocked", "ric": ric, "reason": str(exc),
                                         "disclaimer": INVESTMENT_DISCLAIMER})
        from .reporting import write_blocked_workspace_report
        write_blocked_workspace_report(root / "report.html", ric, snapshot, str(exc))
        raise
    if status == 0 and drafts:
        from .editorial import write_drafts
        write_drafts(root / "valuation", root / "social")
        print(f"Private editorial drafts: {root / 'social'}")
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description="TickerFoundry · Reproducible listed-equity research",
                                     epilog=INVESTMENT_DISCLAIMER)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Prepare a company request and an intentionally incomplete input template")
    init.add_argument("company")
    init.add_argument("--as-of", required=True)
    init.add_argument("--out", required=True)
    init.add_argument("--basis", choices=("enterprise", "common-equity"), default="enterprise")
    demo = commands.add_parser("demo", help="Run the clearly fictional example without credentials or network")
    demo.add_argument("--out", required=True)
    check = commands.add_parser("check", help="Check a normalized case without network calls")
    check.add_argument("--input", required=True)
    check.add_argument("--plan", help="Validate a driver plan and its materialized scenarios")
    run = commands.add_parser("run", help="Calculate a supplied case; optionally call Astra for review")
    run.add_argument("--input", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--plan", help="Materialize three forecasts from a driver plan and underlying facts")
    run.add_argument("--astra", action="store_true", help="Make billed API calls using your own account; requires recorded source permissions")
    research = commands.add_parser("research", help="Make a billed public-web Astra research request from a company name")
    research.add_argument("company")
    research.add_argument("--as-of", required=True)
    research.add_argument("--out", required=True)
    drafts = commands.add_parser("drafts", help="Replay a completed real-company run and write editorial drafts")
    drafts.add_argument("--run", required=True)
    drafts.add_argument("--out", required=True)
    search = commands.add_parser("search", help="Find equity RICs by company name in LSEG Workspace")
    search.add_argument("query")
    analyze = commands.add_parser("analyze", help="Download Workspace data and select the equity valuation method")
    analyze.add_argument("ric", nargs="?", help="Equity ticker, ISIN or primary RIC")
    analyze.add_argument("--from-snapshot", help="Replay a saved workspace_snapshot.json without a data connection")
    analyze.add_argument("--out", help="New output directory (default: runs/lseg/<RIC>-<timestamp>)")
    analyze.add_argument("--drafts", action="store_true", help="Also write private LinkedIn and Instagram drafts")
    for sub in (run, research):
        sub.add_argument("--model", default="gpt-6-astra")
        sub.add_argument("--reasoning", choices=("low", "medium", "high", "xhigh", "max"), default="high")
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            from .lseg_workspace import search as search_workspace
            matches = search_workspace(args.query)
            for match in matches:
                print(f"{match['RIC']}\t{match['DocumentTitle']}")
            if not matches:
                print("No ordinary-share matches. Try the issuer's full name or check Workspace coverage.")
                return 2
            return 0
        if args.command == "analyze":
            return analyze_workspace(args.ric, args.out, args.from_snapshot, args.drafts)
        if args.command == "init":
            case = input_template(args.company, args.as_of, args.basis)
            out = fresh_output(args.out)
            write_json(out / "case.json", case)
            write_json(out / "request.json", {"company_query": args.company, "valuation_date": args.as_of,
                                               "status": "identity_and_inputs_required", "publication_ready": False,
                                               "disclaimer": INVESTMENT_DISCLAIMER})
            print(f"Prepared {out / 'case.json'}; blanks require evidence and assumptions before valuation.")
            return 0
        if args.command == "demo":
            fixture = Path(__file__).resolve().parent.parent / "examples" / "synthetic_company.json"
            if not fixture.exists():
                fixture = Path(__file__).resolve().parent / "resources" / "synthetic_company.json"
            return run_case(fixture, args.out)
        if args.command == "check":
            from .validation import validate_case
            case = load_json(args.input)
            if args.plan:
                from .model import evaluate_plan
                _, result = evaluate_plan(case, load_json(args.plan))
                issues = result["checks"]
            else:
                issues = validate_case(case)
            print(json.dumps(issues, indent=2, allow_nan=False))
            return 2 if any(i["severity"] == "error" for i in issues) else 0
        if args.command == "run":
            return run_case(args.input, args.out, args.astra, args.model, args.reasoning, args.plan)
        if args.command == "drafts":
            from .editorial import write_drafts
            write_drafts(Path(args.run), args.out)
            print(f"Editorial drafts: {args.out}")
            return 0
        if args.command == "research":
            date.fromisoformat(args.as_of)
            from .astra import run_research
            out = fresh_output(args.out)
            dossier = run_research(args.company, args.as_of, model=args.model, reasoning_effort=args.reasoning)
            write_json(out / "research.json", dossier)
            write_research_report(out / "research.html", dossier)
            print(f"Research draft: {out / 'research.html'}; not a verified valuation.")
            return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError, EOFError) as exc:
        print(f"Could not complete the request: {exc}", file=sys.stderr)
        return 2
    return 0
