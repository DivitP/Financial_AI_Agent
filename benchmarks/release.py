"""Fail-closed offline release gates with per-stage logs and JSON/Markdown summaries."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def python_results(path, *, require_scaled=False):
    cases = ET.parse(path).getroot().findall(".//testcase")
    skipped = [c for c in cases if c.find("skipped") is not None]
    unexpected = [c for c in skipped if "test_deployment_profiles" not in c.get("classname", "")]
    failures = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    corpus = [c for c in cases if "test_release_corpus" in c.get("classname", "")]
    passed = (
        bool(cases)
        and not failures
        and not unexpected
        and len(skipped) <= (0 if require_scaled else 6)
        and len(corpus) == 12
    )
    return passed, {
        "tests": len(cases),
        "failures": len(failures),
        "skipped_scaled": len(skipped),
        "corpus_cases": len(corpus),
    }


def browser_results(path):
    stats = json.loads(path.read_text())["stats"]
    passed = stats["expected"] >= 15 and all(
        stats[key] == 0 for key in ("unexpected", "flaky", "skipped")
    )
    return passed, stats


def run_stage(name, command, output, *, env=None, validate=None):
    start = time.monotonic()
    status, details = "failed", {}
    try:
        with (output / f"{name}.log").open("w") as log:
            result = subprocess.run(
                command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900
            )
        details["exit_code"] = result.returncode
        if result.returncode == 0:
            status = "passed"
            if validate:
                valid, counts = validate()
                details.update(counts)
                status = "passed" if valid else "failed"
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ET.ParseError,
        subprocess.TimeoutExpired,
    ) as error:
        # Do not copy exception contents, paths or credentials into the summary.
        status = "failed"
        details["error"] = type(error).__name__
    return {
        "name": name,
        "status": status,
        "seconds": round(time.monotonic() - start, 2),
        "log": f"{name}.log",
        **details,
    }


def main():
    output = (
        ROOT
        / "data/runtime/release"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    )
    output.mkdir(parents=True)
    python = sys.executable
    env = {**os.environ, "CI": "true", "PLAYWRIGHT_JSON_OUTPUT_NAME": str(output / "browser.json")}
    stages = [
        ("lint", [python, "-m", "ruff", "check", "."], None),
        ("format", [python, "-m", "ruff", "format", "--check", "."], None),
        ("typing", [python, "-m", "mypy"], None),
        (
            "python",
            [python, "-m", "pytest", f"--junitxml={output / 'python.xml'}"],
            lambda: python_results(
                output / "python.xml",
                require_scaled=bool(env.get("TEST_POSTGRES_URL") or env.get("TEST_REDIS_URL")),
            ),
        ),
        ("frontend", ["make", "frontend-lint", "frontend-test", "frontend-build"], None),
        ("performance", [python, "-m", "benchmarks.system"], None),
        (
            "browser",
            [
                "npm",
                "--prefix",
                "frontend/web",
                "run",
                "test:e2e",
                "--",
                "--config",
                "playwright.release.config.ts",
                "--reporter=json",
                "--output",
                str(output / "browser-artifacts"),
            ],
            lambda: browser_results(output / "browser.json"),
        ),
    ]
    results = []
    for name, command, validate in stages:
        print(f"Release gate: {name}", flush=True)
        if (
            name == "browser"
            and next(r for r in results if r["name"] == "frontend")["status"] != "passed"
        ):
            results.append({"name": name, "status": "blocked", "seconds": 0, "log": None})
        else:
            results.append(run_stage(name, command, output, env=env, validate=validate))
    passed = all(r["status"] == "passed" for r in results)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    )
    corpus = ROOT / "tests/fixtures/system/corpus.json"
    report = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "automated_status": "passed" if passed else "failed",
        "manual_visual_review": "required",
        "revision": revision.stdout.strip(),
        "dirty_worktree": bool(dirty.stdout),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "stages": results,
        "exclusions": [
            "Live providers and live LLM quality",
            "Real Kronos weights/GPU",
            "Scaled services when not configured",
        ],
    }
    (output / "quality.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Release candidate quality report",
        "",
        f"Automated gates: **{report['automated_status']}**",
        f"Revision: `{report['revision']}`; dirty worktree: `{report['dirty_worktree']}`.",
        "",
        "Manual screenshot review: **required**. This is not an investment-quality certification.",
        "",
        "| Gate | Status | Seconds | Log |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {r['name']} | {r['status']} | {r['seconds']} | [{r['log']}]({r['log']}) |"
        for r in results
    ]
    lines += [
        "",
        "See quality.json for test counts, corpus hash and exclusions; python.xml and browser.json for individual cases.",
        "Review browser-artifacts screenshots and any failure traces. Logs are local artifacts; inspect before sharing.",
    ]
    (output / "quality.md").write_text("\n".join(lines) + "\n")
    print(f"Quality report: {output / 'quality.md'}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
