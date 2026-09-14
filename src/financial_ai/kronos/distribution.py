"""Empirical model-sample summaries, never calibrated forecast confidence."""

from datetime import date
from decimal import Decimal

from financial_ai.kronos.preprocessing import Candle


def percentile(values: list[Decimal], q: int) -> Decimal:
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: list[Decimal]) -> dict:
    return {
        "samples": [str(v) for v in values],
        "mean": str(sum(values) / len(values)),
        "percentiles": {str(q): str(percentile(values, q)) for q in [5, 25, 50, 75, 95]},
    }


def summarize_paths(raw: list, *, sessions: list[date], count: int, last_close: Decimal) -> dict:
    if len(raw) != count or not raw:
        raise ValueError("Forecast path count mismatch")
    paths = [[Candle.model_validate(row) for row in path] for path in raw]
    if any([c.session for c in path] != sessions for path in paths) or not sessions:
        raise ValueError("Forecast output sessions do not match requested horizon")
    if last_close <= 0 or not last_close.is_finite():
        raise ValueError("Reference close must be finite and positive")
    median, bands = [], []
    for i, session in enumerate(sessions):
        fields = {
            name: [getattr(path[i], name) for path in paths]
            for name in ["open", "high", "low", "close", "volume"]
        }
        median.append(
            Candle(
                session=session, **{name: percentile(values, 50) for name, values in fields.items()}
            ).model_dump(mode="json")
        )
        bands.append(
            {
                "session": session.isoformat(),
                "close_percentiles": distribution(fields["close"])["percentiles"],
            }
        )
    returns = [path[-1].close / last_close - 1 for path in paths]
    volatility = []
    if len(sessions) > 1:
        for path in paths:
            prices = [last_close] + [c.close for c in path]
            changes = [b / a - 1 for a, b in zip(prices, prices[1:])]
            mean = sum(changes) / len(changes)
            volatility.append((sum((r - mean) ** 2 for r in changes) / (len(changes) - 1)).sqrt())
    return {
        "paths": [[c.model_dump(mode="json") for c in path] for path in paths],
        "candles": median,
        "summary": {
            "basis": "uncalibrated empirical model samples",
            "sample_count": count,
            "reference_close": str(last_close),
            "bands": bands,
            "direction_probability": {
                "up": sum(r > 0 for r in returns) / count,
                "flat": sum(r == 0 for r in returns) / count,
                "down": sum(r < 0 for r in returns) / count,
            },
            "terminal_return": distribution(returns),
            "session_volatility": distribution(volatility) if volatility else None,
            "units": {"terminal_return": "fraction", "session_volatility": "fraction_per_session"},
            "volatility_limitation": None
            if volatility
            else "At least two forecast sessions required",
        },
    }
