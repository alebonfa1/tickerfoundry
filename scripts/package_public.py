"""Create an allowlisted source archive, never an archive of private run data."""

from pathlib import Path
import argparse
import json
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "README.md", "LICENSE", "AGENTS.md", "pyproject.toml", ".gitignore", ".env.example",
    ".github/workflows/tests.yml",
    "docs/ANALYSIS_PROTOCOL.md", "docs/DATA_RIGHTS.md", "docs/VALIDATION.md", "docs/LSEG_WORKSPACE.md",
    "docs/METHODOLOGY.md",
    "equity_workbench/__init__.py", "equity_workbench/__main__.py", "equity_workbench/astra.py",
    "equity_workbench/cli.py", "equity_workbench/core.py", "equity_workbench/common_equity.py", "equity_workbench/editorial.py",
    "equity_workbench/evidence.py", "equity_workbench/model.py", "equity_workbench/reporting.py",
    "equity_workbench/lseg_workspace.py", "equity_workbench/lseg_analysis.py", "equity_workbench/equity_models.py",
    "equity_workbench/validation.py", "equity_workbench/resources/synthetic_company.json",
    "examples/synthetic_company.json", "prompts/accounting.md", "prompts/business_risk.md",
    "prompts/critical_reviewer.md", "prompts/research.md", "schemas/company.schema.json",
    "scripts/package_public.py", "tests/test_astra.py", "tests/test_cli.py", "tests/test_core.py",
    "tests/test_validation.py", "tests/test_model.py", "tests/test_lseg.py", "tests/test_equity_models.py",
    "tests/test_common_equity.py",
}


def selected_files(root=ROOT):
    selected = []
    root = root.resolve()
    for name in sorted(FILES):
        path = root / name
        if not path.is_file() or path.resolve() != path:
            raise ValueError(f"Missing or linked allowlisted file: {name}")
        if name.endswith("synthetic_company.json"):
            if json.loads(path.read_text(encoding="utf-8"))["synthetic"] is not True:
                raise ValueError("Public examples must be explicitly fictional JSON fixtures")
        selected.append(path)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    destination = Path(args.out).resolve()
    if destination.exists():
        raise ValueError("Refusing to overwrite an existing archive")
    files = selected_files()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, Path("tickerfoundry") / path.relative_to(ROOT))
    print(f"Created {destination.name} with {len(files)} allowlisted files. Review contents before publishing.")


if __name__ == "__main__":
    main()
