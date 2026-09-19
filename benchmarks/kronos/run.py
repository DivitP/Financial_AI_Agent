"""Reproducible, explicitly invoked synthetic benchmark; no network or downloads."""

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from zoneinfo import ZoneInfo

from financial_ai.analysis.forecast_evaluation import accuracy, kronos_prediction
from financial_ai.kronos import load_manifest
from financial_ai.kronos.inference import InferenceConfig, LocalKronosProvider
from financial_ai.kronos.preprocessing import Candle, CorporateAction, Session, prepare_candles

ROOT = Path(__file__).parent


class FixtureProvider(LocalKronosProvider):
    def _worker_command(self):
        return [sys.executable, "-m", "benchmarks.kronos.fixture_worker"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(case, days):
    zone = ZoneInfo("America/New_York")
    schedule = [
        Session(day=datetime(2026, 9, d).date(), closes_at=datetime(2026, 9, d, 16, tzinfo=zone))
        for d in days
    ]
    context = case.get("context", 8)
    candles = []
    for i, price in enumerate(case["prices"][:context]):
        split = case.get("split") and i < 4
        candles.append(
            Candle(
                session=schedule[i].day,
                open=price * (2 if split else 1),
                high=price * (2 if split else 1),
                low=price * (2 if split else 1),
                close=price * (2 if split else 1),
                volume=None if case.get("reject") == "volume" else 50 if split else 100,
            )
        )
    actions = (
        [
            CorporateAction(
                id="fixture-split",
                kind="split",
                effective_session=schedule[4].day,
                known_at=schedule[2].closes_at,
                split_ratio=2,
            )
        ]
        if case.get("split")
        else []
    )
    prepared = prepare_candles(
        candles,
        sessions=schedule,
        actions=actions,
        as_of=schedule[context - 1].closes_at,
        timezone=str(zone),
        currency="USD",
        provider="synthetic-benchmark",
        calendar_source="fixture-XNYS-2026-09",
        input_policy="raw",
        actions_complete=True,
        horizon=3,
    )
    return prepared.model_copy(update={"instrument": case["symbol"]}), case["prices"][
        context : context + 3
    ]


def hardware():
    packages = {}
    for name in ["torch", "numpy", "pandas", "pydantic"]:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unreported",
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "packages": packages,
    }


def run_suite(
    *,
    mode="fixture",
    device="cpu",
    assets=Path("data/runtime/kronos"),
    source=Path("data/runtime/kronos/source"),
    reference=None,
):
    if mode not in {"fixture", "local"} or (mode == "fixture" and device != "cpu"):
        raise ValueError("Fixture mode requires CPU; mode must be fixture or local")
    catalog = json.loads((ROOT / "cases.json").read_text())
    thresholds = json.loads((ROOT / "thresholds.json").read_text())
    golden = json.loads((ROOT / "golden.json").read_text())
    config = InferenceConfig(
        device=device,
        seed=17,
        sample_count=8,
        timeout_seconds=600 if mode == "local" else 10,
        cache_ttl_seconds=3600,
    )
    identity = {
        "mode": mode,
        "device": device,
        "fixtures_hash": digest(catalog),
        "thresholds_hash": digest(thresholds),
        "manifest": load_manifest().model_dump(mode="json"),
        "configuration": config.model_dump(),
        "environment": hardware(),
        "lock_sha256": hashlib.sha256((ROOT.parents[1] / "uv.lock").read_bytes()).hexdigest(),
    }
    results, failures = [], []
    if reference is not None and reference["identity"] != identity:
        raise ValueError("Reference environment/configuration/fixtures do not match")
    for case in catalog["cases"]:
        start = time.perf_counter()
        row = {
            "id": case["id"],
            "symbol": case["symbol"],
            "asset_type": case["asset_type"],
            "regime": case["regime"],
        }
        try:
            try:
                prepared, actual = prepare(case, catalog["sessions"])
            except ValueError as exc:
                if case.get("reject") and case["reject"] in str(exc):
                    row.update(status="expected_rejection", reason=case["reject"])
                    results.append(row)
                    continue
                raise
            if case.get("reject"):
                raise AssertionError("Malformed input was accepted")
            if case.get("split"):
                assert len({b.close for b in prepared.candles}) == 1
                assert len({b.volume for b in prepared.candles}) == 1
            # Distinct caches ensure both repeat forecasts execute actual workers.
            with tempfile.TemporaryDirectory(prefix="kronos-benchmark-") as temp:
                provider_type = FixtureProvider if mode == "fixture" else LocalKronosProvider
                providers = [
                    provider_type(
                        enabled=True,
                        assets=assets,
                        source=source,
                        cache=Path(temp) / f"{i}.sqlite3",
                        config=config,
                    )
                    for i in range(2)
                ]
                outputs, durations = [], []
                for provider in providers:
                    began = time.perf_counter()
                    outputs.append(provider.forecast(prepared))
                    durations.append(time.perf_counter() - began)
                first, second = outputs
                assert (
                    first["paths"] == second["paths"] and first["summary"] == second["summary"]
                ), "Fixed-seed regression"
                assert not first["cache_hit"] and not second["cache_hit"]
                began = time.perf_counter()
                cached = providers[0].forecast(prepared)
                cache_seconds = time.perf_counter() - began
                assert cached["cache_hit"] and cached["paths"] == first["paths"]
            metrics = accuracy(
                [float(c.close) for c in prepared.candles], actual, kronos_prediction(first)
            )
            if mode == "fixture":
                assert [digest(first["paths"]), digest(first["summary"])] == golden[case["id"]], (
                    "Fixture golden regression"
                )
            row.update(
                metrics=metrics,
                paths_hash=digest(first["paths"]),
                summary_hash=digest(first["summary"]),
                cold_seconds=durations,
                cache_seconds=cache_seconds,
            )
            limit = thresholds[mode]
            for metric in ["mae", "rmse"]:
                assert metrics[metric] <= limit[f"max_{metric}"], f"{metric} threshold exceeded"
            if reference:
                prior = next(r for r in reference["cases"] if r["id"] == case["id"])
                for metric in ["mae", "rmse"]:
                    bound = (
                        prior["metrics"][metric] * (1 + thresholds["reference_relative_tolerance"])
                        + thresholds["reference_absolute_tolerance"]
                    )
                    assert metrics[metric] <= bound, f"{metric} reference regression"
                assert digest(first["paths"]) == prior["paths_hash"], (
                    "Raw paths changed from approved reference"
                )
            elapsed = time.perf_counter() - start
            assert elapsed <= limit["max_case_seconds"], "Runtime smoke budget exceeded"
            row.update(
                status="passed",
                metrics=metrics,
                paths_hash=digest(first["paths"]),
                summary_hash=digest(first["summary"]),
                cold_seconds=durations,
                cache_seconds=cache_seconds,
                total_seconds=elapsed,
            )
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__)
            if isinstance(exc, AssertionError):
                row["reason"] = str(exc)
            failures.append(case["id"])
        results.append(row)
    divisor = 1024**2 if sys.platform == "darwin" else 1024
    return {
        "identity": identity,
        "created_at": datetime.now(UTC).isoformat(),
        "cases": results,
        "failures": failures,
        "memory": {
            "parent_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor,
            "child_peak_rss_mib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / divisor,
            "scope": "process-lifetime high-water marks, not per-case or GPU memory",
        },
        "limitations": [
            catalog["provenance"],
            "Fixture mode measures a protocol stub, not Kronos accuracy.",
            "Synthetic regression results must never be used as promotion evidence.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture", "local"], default="fixture")
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], default="cpu")
    parser.add_argument("--assets", type=Path, default=Path("data/runtime/kronos"))
    parser.add_argument("--source", type=Path, default=Path("data/runtime/kronos/source"))
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_suite(
        mode=args.mode,
        device=args.device,
        assets=args.assets,
        source=args.source,
        reference=json.loads(args.reference.read_text()) if args.reference else None,
    )
    serialized = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n")
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "cases": len(report["cases"]),
                    "failures": report["failures"],
                    "output": str(args.output),
                }
            )
        )
    else:
        print(serialized)
    return int(bool(report["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
