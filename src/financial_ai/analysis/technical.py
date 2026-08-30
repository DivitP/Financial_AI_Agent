"""Deterministic technical conditions and regimes, never trade commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from collections.abc import Sequence


@dataclass(frozen=True)
class PricePoint:
    timestamp: datetime
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class TechnicalRegime:
    return_1_period: float | None
    volatility: float | None
    max_drawdown: float | None
    short_average: float | None
    long_average: float | None
    rsi: float | None
    relative_volume: float | None
    support: float | None
    resistance: float | None
    trend: str
    momentum: str
    regime: str


def analyze_technical_regime(
    points: list[PricePoint], short_window: int = 5, long_window: int = 20
) -> TechnicalRegime:
    if len(points) < 2:
        return TechnicalRegime(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "insufficient",
            "insufficient",
            "insufficient",
        )
    closes = [point.close for point in points]
    returns = [(current / prior) - 1 for prior, current in zip(closes, closes[1:]) if prior > 0]
    short = _average(closes[-short_window:]) if len(closes) >= short_window else None
    long = _average(closes[-long_window:]) if len(closes) >= long_window else None
    volatility = _std(returns) if len(returns) > 1 else None
    drawdown = _max_drawdown(closes)
    rsi = _rsi(returns)
    average_volume = _average(
        [point.volume for point in points[-long_window:] if point.volume is not None]
    )
    current_volume = points[-1].volume
    relative_volume = (
        current_volume / average_volume if current_volume is not None and average_volume else None
    )
    trend = (
        "uptrend"
        if short is not None and long is not None and short > long
        else "downtrend"
        if short is not None and long is not None and short < long
        else "range_or_insufficient"
    )
    momentum = "positive" if returns[-1] > 0 else "negative" if returns[-1] < 0 else "flat"
    regime = (
        "trending"
        if trend in {"uptrend", "downtrend"} and volatility is not None
        else "range_or_volatile"
    )
    return TechnicalRegime(
        returns[-1] if returns else None,
        volatility,
        drawdown,
        short,
        long,
        rsi,
        relative_volume,
        min(closes[-long_window:]),
        max(closes[-long_window:]),
        trend,
        momentum,
        regime,
    )


def _average(values: Sequence[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return sum(valid) / len(valid) if valid else None


def _std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    drawdowns = []
    for close in closes:
        peak = max(peak, close)
        drawdowns.append((close / peak) - 1)
    return min(drawdowns)


def _rsi(returns: list[float], window: int = 14) -> float | None:
    if not returns:
        return None
    sample = returns[-window:]
    gains = [value for value in sample if value > 0]
    losses = [-value for value in sample if value < 0]
    if not losses:
        return 100.0
    average_gain = sum(gains) / len(sample)
    average_loss = sum(losses) / len(sample)
    return 100 - 100 / (1 + average_gain / average_loss) if average_loss else 100.0
