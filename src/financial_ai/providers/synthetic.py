"""Versioned invented research fixtures. No clocks, network, randomness or real filings."""

import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from typing import Any

from financial_ai.providers.collected import CollectedLane

VERSION = "synthetic-v1"
NOTICE = "SYNTHETIC SAMPLE — all figures and organizations are invented. Not a real filing or investment research."
AS_OF = datetime(2025, 12, 31, 21, tzinfo=UTC)
SYMBOLS = ("AAPL", "MSFT", "NVDA", "SPY", "QQQ")
LANES = ("instrument", "quote", "ohlcv", "filings", "statements", "news")


def record_id(symbol: str, lane: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"financial-ai:{VERSION}:{symbol}:{lane}")


class SyntheticCollector:
    """Implements the same collect(lane, run) boundary as LiveCollector."""

    def __init__(self, base_url="http://localhost:8000"):
        from pydantic import HttpUrl, TypeAdapter

        url = TypeAdapter(HttpUrl).validate_python(base_url)
        if url.username or url.password or url.query or url.fragment or url.path not in {None, "/"}:
            raise ValueError(
                "Synthetic evidence base must be an HTTP(S) origin without credentials"
            )
        self.base_url = str(url).rstrip("/")

    def collect(self, lane, run) -> CollectedLane:
        symbol = run["symbol"]
        if symbol not in SYMBOLS:
            raise ValueError("Unsupported synthetic symbol; choose AAPL, MSFT, NVDA, SPY or QQQ")
        if lane not in LANES:
            raise ValueError("Unsupported synthetic collection lane")
        scale = SYMBOLS.index(symbol) + 1
        asset = "etf" if symbol in {"SPY", "QQQ"} else "equity"
        url = f"{self.base_url}/api/v1/synthetic-evidence/{record_id(symbol, lane)}"
        common = dict(
            synthetic=True,
            dataset_version=VERSION,
            notice=NOTICE,
            symbol=symbol,
            provider=VERSION,
            as_of=AS_OF.isoformat(),
            currency="USD",
            unit="USD",
            timezone="UTC",
            adjustment_policy="synthetic_unadjusted_no_corporate_actions",
        )
        days: list[datetime] = []
        day = AS_OF
        while len(days) < 60:
            if day.weekday() < 5:
                days.append(day)
            day -= timedelta(days=1)
        candles = [
            dict(
                timestamp=day.isoformat(),
                open=100 * scale + i - 0.5,
                high=100 * scale + i + 1,
                low=100 * scale + i - 1,
                close=100 * scale + i,
                volume=100000 * scale + i * 100,
            )
            for i, day in enumerate(reversed(days))
        ]
        facts = []
        for year, revenue in ((2023, 800000), (2024, 1000000)):
            for tag, value, instant in (
                ("Revenues", revenue, False),
                ("GrossProfit", revenue * 39 // 100, False),
                ("NetIncomeLoss", revenue // 5, False),
                ("OperatingIncomeLoss", revenue // 4, False),
                ("StockholdersEquity", revenue // 2, True),
                ("AssetsCurrent", revenue * 3 // 5, True),
                ("LiabilitiesCurrent", revenue // 5, True),
                ("PaymentsToAcquirePropertyPlantAndEquipment", revenue // 20, False),
                ("ShareBasedCompensation", revenue // 50, False),
            ):
                facts.append(
                    dict(
                        tag=tag,
                        taxonomy="synthetic",
                        value=str(value * scale),
                        unit="USD",
                        period_start=None if instant else f"{year}-01-01",
                        period_end=f"{year}-12-31",
                        filed_at=f"{year + 1}-02-01",
                        accepted_at=f"{year + 1}-02-01T12:00:00+00:00",
                        form="SYNTHETIC-ANNUAL",
                        accession_number=f"sample-{symbol}-{year}",
                        synthetic=True,
                        source_url=f"{self.base_url}/api/v1/synthetic-evidence/{record_id(symbol, 'statements')}",
                    )
                )
        values: dict[str, dict[str, Any]] = {
            "instrument": dict(
                name=f"Synthetic {symbol} {'Fund' if asset == 'etf' else 'Company'} (fictional)",
                asset_type=asset,
                exchange="SYNTHETIC",
                cik=None,
            ),
            "quote": dict(
                price=candles[-1]["close"], volume=candles[-1]["volume"], volume_unit="shares"
            ),
            "ohlcv": dict(
                candles=candles,
                volume_unit="shares",
                calendar="invented weekday schedule, not an exchange calendar",
            ),
            "statements": dict(facts=[] if asset == "etf" else facts),
            "filings": dict(
                items=[]
                if asset == "etf"
                else [
                    dict(
                        form="SYNTHETIC-ANNUAL",
                        title="Invented annual financial sample — not an SEC filing",
                        filed_at="2025-02-01T12:00:00+00:00",
                        url=url,
                        accession_number=f"sample-{symbol}-2024",
                        synthetic=True,
                    )
                ]
            ),
            "news": dict(
                articles=[
                    dict(
                        title=f"Synthetic {symbol} sample event (invented)",
                        canonical_url=url,
                        publisher="Synthetic fixture generator",
                        author="Fixture generator",
                        published_at=AS_OF.isoformat(),
                        retrieved_at=AS_OF.isoformat(),
                        synthetic=True,
                    )
                ]
            ),
        }
        payload = {**common, **values[lane]}
        text = f"{NOTICE}\n{symbol} {lane}\n" + json.dumps(payload, sort_keys=True)
        # Chart arrays belong in artifacts/snapshots, never retrieval text.
        if lane == "ohlcv":
            text = f"{NOTICE}\n{symbol}: 60 invented daily prices; final close {candles[-1]['close']} USD."
        return CollectedLane(
            provider=VERSION,
            url=url,
            retrieved_at=AS_OF,
            published_at=AS_OF,
            text=text,
            payload=payload,
            limitations=[NOTICE],
        )

    def lookup(self, ident: UUID) -> CollectedLane:
        for symbol in SYMBOLS:
            for lane in LANES:
                if record_id(symbol, lane) == ident:
                    return self.collect(lane, {"symbol": symbol})
        raise KeyError("Unknown synthetic evidence record")
