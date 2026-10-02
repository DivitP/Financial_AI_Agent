"""Negative controls ensure release reports cannot turn missing checks green."""

import json
import sys

from benchmarks.release import browser_results, python_results, run_stage


def test_failed_or_missing_stage_is_reported_and_keeps_a_log(tmp_path):
    result = run_stage("broken", [sys.executable, "-c", "raise SystemExit(3)"], tmp_path)
    assert result["status"] == "failed" and result["exit_code"] == 3
    assert (tmp_path / "broken.log").exists()
    result = run_stage("missing", [str(tmp_path / "missing-command")], tmp_path)
    assert result["status"] == "failed"
    result = run_stage(
        "empty",
        [sys.executable, "-c", "pass"],
        tmp_path,
        validate=lambda: python_results(tmp_path / "absent.xml"),
    )
    assert result["status"] == "failed"


def test_browser_threshold_rejects_flakes_skips_and_empty_runs(tmp_path):
    path = tmp_path / "browser.json"
    for field in ("unexpected", "flaky", "skipped"):
        stats = dict(expected=15, unexpected=0, flaky=0, skipped=0)
        stats[field] = 1
        path.write_text(json.dumps({"stats": stats}))
        assert not browser_results(path)[0]
    path.write_text(json.dumps({"stats": dict(expected=0, unexpected=0, flaky=0, skipped=0)}))
    assert not browser_results(path)[0]


def test_python_threshold_requires_corpus_and_rejects_unexpected_skips(tmp_path):
    path = tmp_path / "python.xml"
    path.write_text("<testsuites><testsuite/></testsuites>")
    assert not python_results(path)[0]
    cases = '<testcase classname="tests.test_release_corpus"/>' * 12
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    assert python_results(path)[0]
    path.write_text(
        f'<testsuites><testsuite>{cases}<testcase classname="tests.test_deployment_profiles"><skipped/></testcase></testsuite></testsuites>'
    )
    assert python_results(path)[0]
    assert not python_results(path, require_scaled=True)[0]
    path.write_text(
        f'<testsuites><testsuite>{cases}<testcase classname="required"><skipped/></testcase></testsuite></testsuites>'
    )
    assert not python_results(path)[0]
