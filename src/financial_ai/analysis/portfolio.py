"""Hypothetical long-only portfolio context from saved, aligned observations."""

import json
import math
from contextlib import closing
from datetime import date
from statistics import correlation, stdev

from financial_ai.analysis.compare import ResearchComparison


def number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite value")
    return result


def concentration(weights):
    return {
        "weights": weights,
        "largest_weight": max(weights.values()),
        "hhi": sum(w * w for w in weights.values()),
    }


def path_risk(returns, weights):
    daily = [
        sum(weights.get(t, 0) * returns[t][i] for t in returns)
        for i in range(len(next(iter(returns.values()))))
    ]
    wealth = peak = 1.0
    drawdown = 0.0
    for value in daily:
        wealth *= 1 + value
        if not math.isfinite(wealth) or wealth <= 0:
            raise ValueError("Price path cannot produce finite positive portfolio wealth")
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - 1)
    return {"daily_volatility": stdev(daily), "max_drawdown": drawdown}


def risk_comparison(data, before, after):
    """Same sessions for both portfolios; never forward-fill or omit a holding."""
    try:
        if any("ohlcv" not in data.get(t, {}) for t in after):
            raise ValueError("Missing cited saved price history for one or more tickers")
        histories = {t: data[t]["ohlcv"] for t in after}
        for field in ("currency", "timezone", "adjustment_policy", "interval"):
            values = [p.get(field) for p in histories.values()]
            if any(not isinstance(v, str) or not v for v in values) or len(set(values)) != 1:
                raise ValueError(f"Different or missing {field}")
        example = next(iter(histories.values()))
        if example["interval"] != "1d" or example["adjustment_policy"] not in (
            "split",
            "split_and_dividend",
        ):
            raise ValueError("Requires daily, explicitly adjusted prices")
        prices = {}
        for ticker, payload in histories.items():
            points = {}
            if len(payload["bars"]) > 2521:
                raise ValueError("Price history exceeds the 2521-session limit")
            for bar in payload["bars"]:
                session = date.fromisoformat(bar["session"]).isoformat()
                close = number(bar["close"])
                if close <= 0 or session in points:
                    raise ValueError("Nonpositive close or duplicate session")
                points[session] = close
            prices[ticker] = points
        common = sorted(set.intersection(*(set(p) for p in prices.values())))
        if len(common) < 21:
            raise ValueError("At least 21 common daily prices are required")
        # Every source must contain the same session grid within the overlap.
        if any(
            [s for s in sorted(p) if common[0] <= s <= common[-1]] != common
            for p in prices.values()
        ):
            raise ValueError("Missing or incompatible sessions within the overlap")
        returns = {
            t: [p[b] / p[a] - 1 for a, b in zip(common, common[1:])] for t, p in prices.items()
        }
        if any(not math.isfinite(r) for series in returns.values() for r in series):
            raise ValueError("Non-finite return")
        correlations = {}
        for a in returns:
            correlations[a] = {
                b: correlation(returns[a], returns[b])
                if stdev(returns[a]) > 0 and stdev(returns[b]) > 0
                else None
                for b in returns
            }
        old, new = path_risk(returns, before), path_risk(returns, after)
        return {
            "available": True,
            "start": common[0],
            "end": common[-1],
            "observations": len(common) - 1,
            "currency": example["currency"],
            "adjustment_policy": example["adjustment_policy"],
            "correlations": correlations,
            "before": old,
            "after": new,
            "change": {k: new[k] - old[k] for k in old},
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"available": False, "reason": str(exc)}


def exposures(data, weights):
    sectors: dict[str, float] = {}
    factors: dict[str, dict] = {}
    for ticker, weight in weights.items():
        saved = data[ticker]
        breakdown = (
            saved.get("etf", {}).get("sector_exposure")
            if saved.get("asset_type") == "etf"
            else {saved.get("instrument", {}).get("sector", "Unknown"): 1.0}
        )
        try:
            values = {str(k): number(v) for k, v in breakdown.items()}
            if any(v < 0 for v in values.values()) or sum(values.values()) > 1.000001:
                raise ValueError("Invalid sector weights")
        except (AttributeError, TypeError, ValueError):
            values = {}
        values["Unknown"] = values.get("Unknown", 0) + max(0, 1 - sum(values.values()))
        for sector, value in values.items():
            sectors[sector] = sectors.get(sector, 0) + value * weight
        # Factor loadings remain separate by model; never equate unlike betas.
        factor = saved.get("factors", {})
        model = factor.get("model")
        if isinstance(model, str) and isinstance(factor.get("loadings"), dict):
            for name, loading in factor["loadings"].items():
                try:
                    value = number(loading)
                except (TypeError, ValueError):
                    continue
                key = model + ":" + name
                group = factors.setdefault(key, {"weighted_loading": 0.0, "covered_weight": 0.0})
                group["weighted_loading"] += value * weight
                group["covered_weight"] += weight
    return {
        "sector_weights": sectors,
        "factor_loadings": factors,
        "factor_note": "Model-specific partial weighted loadings; missing exposure is unknown, not zero.",
    }


class PortfolioContext:
    def __init__(self, database):
        self.database = database

    def analyze(self, holdings, candidate):
        before = {h.ticker: h.weight / 100 for h in holdings}
        after = {t: w * (1 - candidate.weight / 100) for t, w in before.items()}
        after[candidate.ticker] = after.get(candidate.ticker, 0) + candidate.weight / 100
        data: dict[str, dict] = {}
        sources: dict[str, dict] = {}
        with closing(self.database.connect()) as db:
            for ticker in after:
                data[ticker] = {}
                instruments = db.execute(
                    "SELECT * FROM instruments WHERE symbol=?", (ticker,)
                ).fetchall()
                sources[ticker] = {
                    "run_id": None,
                    "lanes": {},
                    "limitation": "No unique saved instrument or terminal run",
                }
                if len(instruments) != 1:
                    continue
                instrument = instruments[0]
                data[ticker]["asset_type"] = instrument["asset_type"]
                run = db.execute(
                    """SELECT * FROM research_runs WHERE instrument_id=? AND status NOT IN ('pending','running')
                    ORDER BY julianday(requested_at) DESC,id DESC LIMIT 1""",
                    (instrument["id"],),
                ).fetchone()
                if not run:
                    continue
                sources[ticker] = {
                    "run_id": run["id"],
                    "requested_at": run["requested_at"],
                    "status": run["status"],
                    "lanes": {},
                }
                for row in db.execute(
                    "SELECT * FROM research_snapshots WHERE run_id=?", (run["id"],)
                ):
                    if (
                        row["lane"] not in ("ohlcv", "instrument", "etf", "factors")
                        or row["status"] != "completed"
                    ):
                        continue
                    payload = json.loads(row["payload_json"] or "{}")
                    if not isinstance(payload, dict):
                        continue
                    citations = ResearchComparison(self.database)._citations(payload, run["id"], db)
                    sources[ticker]["lanes"][row["lane"]] = {
                        "evidence": citations,
                        "retrieved_at": payload.get("retrieved_at"),
                        "provider": payload.get("provider"),
                    }
                    if citations:
                        data[ticker][row["lane"]] = payload
        return {
            "before": concentration(before) | exposures(data, before),
            "after": concentration(after) | exposures(data, after),
            "historical_risk": risk_comparison(data, before, after),
            "sources": sources,
            "limitations": [
                "Hypothetical research, not personalized advice, optimization, or a trading instruction.",
                "Candidate allocation proportionally reduces existing weights; no leverage, shorts or cash.",
                "Historical risk uses constant weights (daily rebalancing), no fees or taxes, and the same overlap for both portfolios.",
                "Split-only prices exclude dividend return. Correlations and drawdowns are historical, not forecasts.",
                "Concentration is by ticker, not constituent look-through; ETF overlap can hide concentration.",
                "Saved data may be stale. Uncited or unavailable observations are excluded and risk is withheld if any price series is missing.",
            ],
        }
