import json
import os
from copy import deepcopy

import pytest

from benchmarks.kronos.run import ROOT, prepare, run_suite

pytestmark = pytest.mark.kronos_benchmark


def test_fixture_suite_thresholds_and_repeatability():
    first = run_suite()
    assert not first["failures"], first["cases"]
    assert len(first["cases"]) == 9
    second = run_suite(reference=first)
    assert not second["failures"], second["cases"]
    assert {r["id"] for r in first["cases"] if r["status"] == "expected_rejection"} == {
        "missing_volume",
        "one_session",
    }
    bad = deepcopy(first)
    bad["cases"][0]["paths_hash"] = "intentional-regression"
    assert "aapl_trend" in run_suite(reference=bad)["failures"]
    bad["identity"]["device"] = "cuda"
    with pytest.raises(ValueError, match="do not match"):
        run_suite(reference=bad)


def test_split_normalization_and_calendar():
    catalog = json.loads((ROOT / "cases.json").read_text())
    case = next(c for c in catalog["cases"] if c["id"] == "aapl_split")
    prepared, _ = prepare(case, catalog["sessions"])
    assert {b.close for b in prepared.candles} == {100}
    assert {b.volume for b in prepared.candles} == {100}
    assert all(t.day != 7 for t in prepared.historical_timestamps + prepared.future_timestamps)


@pytest.mark.skipif(
    os.environ.get("KRONOS_BENCHMARK_LOCAL") != "1", reason="Explicit local-weight opt-in required"
)
def test_real_local_weights():
    report = run_suite(mode="local", device=os.environ.get("KRONOS_BENCHMARK_DEVICE", "cpu"))
    assert not report["failures"], report["cases"]
