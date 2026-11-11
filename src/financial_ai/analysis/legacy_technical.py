"""Historical technical report for Flask; no unvalidated forecast or trade commands."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import asdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib.figure import Figure

from financial_ai.analysis.technical import PricePoint, analyze_technical_regime
from financial_ai.providers.legacy_live import LegacyLiveProvider, symbol
from financial_ai.storage.artifacts import FileSystemArtifactStore


def build_technical_report(ticker: str, *, settings=None, provider=None) -> dict:
    from settings import get_settings

    settings = settings or get_settings()
    provider = provider or LegacyLiveProvider(settings)
    ticker = symbol(ticker)
    try:
        frame, record = provider.history(ticker)
    except ValueError:
        return dict(
            status="error",
            text="Historical technical analysis unavailable: "
            "neither configured history source supplied enough valid observations.",
            tech_image=None,
            bollinger_image=None,
            arima_image=None,
            garch_image=None,
        )
    store = FileSystemArtifactStore(Path(settings.persist_dir) / "legacy_evidence")
    evidence = store.put_text(json.dumps(asdict(record), sort_keys=True), category="source")
    profile = provider.fmp("profile", ticker)
    currency = profile.data[0].get("currency") if profile.data else None
    if not currency and record.provider == "Yahoo Finance" and record.data:
        currency = record.data[0].get("meta", {}).get("currency")
    currency = currency or "currency unavailable"
    points = [
        PricePoint(stamp.to_pydatetime(), float(row.Close), float(row.Volume))
        for stamp, row in frame.iterrows()
    ]
    regime = analyze_technical_regime(points)
    lines = [
        f"HISTORICAL TECHNICAL CONDITIONS — {ticker}",
        f"Provider: {record.provider} | Last observation date: {frame.index[-1].date()}",
        f"Retrieved: {record.retrieved_at} | Currency: {currency} | Unit: price/share",
        "Adjustment: provider OHLCV as supplied; corporate-action policy not verified.",
        f"Source: {record.url}",
        f"Evidence: {evidence}",
        f"Observations: {len(frame)} | Last close: {frame.Close.iloc[-1]:,.2f}",
        f"Trend: {regime.trend} | Momentum: {regime.momentum}",
        f"5-observation average: {regime.short_average:,.2f}",
        f"20-observation average: {regime.long_average:,.2f}",
        f"RSI (simple return-based): {regime.rsi:.2f}",
        f"Maximum drawdown over observed window: {regime.max_drawdown:.2%}",
        "Historical descriptions only, not buy/sell instructions.",
        "Forecasts withheld: no relevant out-of-sample calibration is available.",
        *record.notices,
    ]
    images = []
    for bands in (False, True):
        figure = Figure(figsize=(11, 4), layout="constrained")
        ax = figure.subplots()
        ax.plot(frame.index, frame.Close, label="Historical close", color="#147569")
        mean = frame.Close.rolling(20).mean()
        ax.plot(frame.index, mean, label="20-observation average", color="#4a6599")
        if bands:
            spread = frame.Close.rolling(20).std() * 2
            ax.fill_between(
                frame.index,
                mean - spread,
                mean + spread,
                color="#4a6599",
                alpha=0.15,
                label="Historical bands (±2 rolling standard deviations)",
            )
        ax.set_title(f"{ticker} · {record.provider} · historical observations only")
        ax.set_ylabel(f"Price / share ({currency})")
        ax.set_xlabel("Observation date · adjustment policy unverified")
        ax.tick_params(axis="x", rotation=25)
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=100)
        images.append(base64.b64encode(buffer.getvalue()).decode())
    return dict(
        status="success",
        sources=[record.url],
        text="\n".join(lines),
        tech_image=images[0],
        bollinger_image=images[1],
        arima_image=None,
        garch_image=None,
    )
