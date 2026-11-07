"""Negative controls for replacement coverage thresholds and measurement scope."""

from copy import deepcopy
from pathlib import Path
import tomllib

import pytest

from benchmarks.coverage import evaluate


def report(lines=87, branches=69):
    return {
        "meta": {"branch_coverage": True},
        "files": {"src/financial_ai/example.py": {}},
        "totals": {
            "covered_lines": lines,
            "num_statements": 100,
            "covered_branches": branches,
            "num_branches": 100,
        },
    }


def test_thresholds_include_exact_boundary_and_reject_each_regression():
    floors = {"lines": 87, "branches": 69}
    assert evaluate(report(), floors)["passed"]
    assert not evaluate(report(lines=86), floors)["passed"]
    assert not evaluate(report(lines=100, branches=68), floors)["passed"]
    # A value that rounds up in the display still fails the unrounded gate.
    almost = report()
    almost["totals"].update(covered_lines=86999, num_statements=100000)
    assert not evaluate(almost, floors)["passed"]


@pytest.mark.parametrize("case", ["no-branches", "no-files", "zero-total", "bad-total"])
def test_incomplete_measurement_fails_closed(case):
    data = deepcopy(report())
    if case == "no-branches":
        data["meta"]["branch_coverage"] = False
    elif case == "no-files":
        data["files"] = {}
    elif case == "zero-total":
        data["totals"]["num_branches"] = 0
    else:
        data["totals"]["covered_lines"] = 101
    with pytest.raises(ValueError):
        evaluate(data, {"lines": 87, "branches": 69})


def test_pytest_uses_configured_replacement_source_without_overriding_it():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())["tool"]
    assert "financial_ai" in config["coverage"]["run"]["source"]
    assert config["coverage"]["run"]["branch"] is True
    options = config["pytest"]["ini_options"]["addopts"].split()
    assert "--cov" in options
    assert not any(option.startswith("--cov=") for option in options)
    assert config["financial-ai"]["coverage"] == {"lines": 87.0, "branches": 69.0}
