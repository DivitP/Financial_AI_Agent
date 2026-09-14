from datetime import date
from decimal import Decimal

import pytest

from financial_ai.kronos.distribution import summarize_paths


def summarize(prices):
    sessions = [date(2026, 9, 14 + i) for i in range(len(prices[0]))]
    paths = [
        [
            dict(session=s, open=p, high=p, low=p, close=p, volume=100)
            for s, p in zip(sessions, path, strict=True)
        ]
        for path in prices
    ]
    return summarize_paths(paths, sessions=sessions, count=len(paths), last_close=Decimal(100))


def test_exact_percentiles_returns_direction_and_volatility():
    result = summarize([[100, 80], [100, 100], [100, 120]])
    summary = result["summary"]
    assert Decimal(result["candles"][-1]["close"]) == 100
    assert {k: Decimal(v) for k, v in summary["bands"][-1]["close_percentiles"].items()} == {
        "5": Decimal(82),
        "25": Decimal(90),
        "50": Decimal(100),
        "75": Decimal(110),
        "95": Decimal(118),
    }
    assert summary["direction_probability"] == dict(up=1 / 3, flat=1 / 3, down=1 / 3)
    assert [Decimal(v) for v in summary["terminal_return"]["samples"]] == [
        Decimal("-.2"),
        0,
        Decimal(".2"),
    ]
    assert Decimal(summary["terminal_return"]["mean"]) == 0
    assert float(summary["session_volatility"]["samples"][0]) == pytest.approx(0.2 / 2**0.5)
    assert summary["units"]["terminal_return"] == "fraction"
    assert "uncalibrated" in summary["basis"]


def test_one_session_and_identical_paths():
    one = summarize([[100]])["summary"]
    assert one["session_volatility"] is None
    assert one["direction_probability"] == dict(up=0, down=0, flat=1)
    identical = summarize([[100, 100]] * 3)["summary"]
    assert all(Decimal(v) == 0 for v in identical["session_volatility"]["samples"])


def test_invalid_paths_are_rejected_not_dropped():
    with pytest.raises(ValueError, match="path count"):
        summarize_paths([], sessions=[date(2026, 9, 14)], count=2, last_close=Decimal(100))
    with pytest.raises(ValueError):
        summarize([[100, "NaN"], [100, 110]])
    with pytest.raises(ValueError):
        summarize([[100, -1]])
