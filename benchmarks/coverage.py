"""Separate replacement/legacy coverage with replacement-only regression gates."""

import argparse
import io
import json
from pathlib import Path
import tomllib

from coverage import Coverage

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "replacement": ["src/financial_ai/*"],
    "legacy": ["agents/*", "frontend/*", "main.py"],
    "shared-settings": ["settings.py"],
}


def evaluate(report, thresholds):
    """Compare unrounded line/branch fractions; empty or line-only reports fail."""
    if not report["meta"].get("branch_coverage") or not report["files"]:
        raise ValueError("Expected nonempty branch coverage; run the full test suite first")
    totals = report["totals"]
    result = {}
    for label, numerator, denominator in (
        ("lines", "covered_lines", "num_statements"),
        ("branches", "covered_branches", "num_branches"),
    ):
        covered, total = totals[numerator], totals[denominator]
        if not 0 <= covered <= total or total <= 0:
            raise ValueError("Invalid or empty coverage totals")
        percent = 100 * covered / total
        result[label] = {"covered": covered, "total": total, "percent": percent}
    result["passed"] = all(result[key]["percent"] >= value for key, value in thresholds.items())
    result["thresholds"] = thresholds
    result["files"] = len(report["files"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/runtime/coverage")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    thresholds = config["tool"]["financial-ai"]["coverage"]
    coverage = Coverage(config_file=str(ROOT / "pyproject.toml"))
    coverage.load()
    results = {}
    for name, patterns in GROUPS.items():
        path = args.output / f"{name}.json"
        coverage.json_report(outfile=str(path), include=patterns)
        report = json.loads(path.read_text())
        results[name] = evaluate(report, thresholds if name == "replacement" else {})
        stream = io.StringIO()
        coverage.report(file=stream, include=patterns, show_missing=True)
        (args.output / f"{name}.txt").write_text(stream.getvalue())
    lines = [
        "# Application coverage",
        "",
        "| Scope | Lines | Branches | Gate |",
        "| --- | --- | --- | --- |",
    ]
    for name, result in results.items():
        line, branch = result["lines"], result["branches"]
        gate = (
            ("passed" if result["passed"] else "FAILED")
            if result["thresholds"]
            else "informational"
        )
        lines.append(
            f"| {name} | {line['covered']}/{line['total']} ({line['percent']:.2f}%) | "
            f"{branch['covered']}/{branch['total']} ({branch['percent']:.2f}%) | {gate} |"
        )
    summary = "\n".join(lines) + "\n"
    (args.output / "summary.md").write_text(summary)
    (args.output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(summary)
    print(f"Detailed missing lines/branches: {args.output}")
    return 0 if all(result["passed"] for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
