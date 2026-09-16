"""Daily session-aligned candles. No exchange calendar or prices are fabricated."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from financial_ai.kronos import load_manifest


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Candle(InputModel):
    session: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    amount: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_range(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC values lie outside the candle range")
        return self


class Session(InputModel):
    day: date
    closes_at: AwareDatetime


class CorporateAction(InputModel):
    id: str = Field(min_length=1)
    effective_session: date
    known_at: AwareDatetime
    kind: Literal["split", "dividend", "other"]
    # Split ratio is new shares / old shares. Dividend factor must come from
    # the provider's documented total-return adjustment; never infer it here.
    split_ratio: Decimal | None = Field(default=None, gt=0)
    price_factor: Decimal | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def required_factor(self):
        if self.kind == "split" and (self.split_ratio is None or self.price_factor is not None):
            raise ValueError("Split requires only a new/old share ratio")
        if self.kind != "split" and self.split_ratio is not None:
            raise ValueError("Only splits accept share ratios")
        return self


class PreparedCandles(InputModel):
    instrument: str | None = None
    candles: list[Candle]
    historical_timestamps: list[AwareDatetime]
    future_timestamps: list[AwareDatetime]
    timezone: str
    currency: str
    provider: str
    calendar_source: str
    as_of: AwareDatetime
    adjustment_policy: str
    applied_actions: list[str]
    missing_sessions: list[date]
    truncated_count: int
    amount_policy: str
    warnings: list[str]


def prepare_candles(
    candles: list[Candle],
    *,
    sessions: list[Session],
    actions: list[CorporateAction],
    as_of: datetime,
    timezone: str,
    currency: str,
    provider: str,
    calendar_source: str,
    input_policy: Literal["raw", "split_adjusted", "total_return_adjusted"],
    actions_complete: bool,
    horizon: int = 5,
    max_context: int = 512,
    missing_policy: Literal["reject", "contiguous_suffix"] = "reject",
) -> PreparedCandles:
    """Use a complete supplied exchange schedule from first candle through horizon.

    Adjustment factors anchor history at the as-of session; future actions block
    preparation because raw future prices would need a separate inverse adjustment.
    """
    zone = ZoneInfo(timezone)
    if as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not provider.strip() or not calendar_source.strip() or len(currency) != 3:
        raise ValueError("Provider, calendar source and three-letter currency are required")
    if input_policy not in {"raw", "split_adjusted", "total_return_adjusted"}:
        raise ValueError("An explicit input adjustment policy is required")
    if missing_policy not in {"reject", "contiguous_suffix"}:
        raise ValueError("Unknown missing-session policy")
    if not actions_complete:
        raise ValueError("Corporate action coverage must be confirmed before preprocessing")
    if not 2 <= max_context <= load_manifest().max_context or not 1 <= horizon <= 512:
        raise ValueError("Context/horizon outside supported bounds")
    schedule = sorted(sessions, key=lambda s: s.day)
    if len({s.day for s in schedule}) != len(schedule):
        raise ValueError("Duplicate calendar sessions")
    if any(s.closes_at.astimezone(zone).date() != s.day for s in schedule):
        raise ValueError("Calendar close does not match exchange-local session date")
    if any(a.closes_at >= b.closes_at for a, b in zip(schedule, schedule[1:])):
        raise ValueError("Calendar closes must increase")
    bars = {bar.session: bar for bar in candles}
    if not bars or len(bars) != len(candles):
        raise ValueError("Empty or duplicate candles")
    completed = {s.day: s for s in schedule if s.closes_at <= as_of}
    if not set(bars).issubset(completed):
        raise ValueError("Candle is on a closed, unknown, or unfinished session")
    expected = [s.day for s in schedule if s.day >= min(bars) and s.closes_at <= as_of]
    missing = [day for day in expected if day not in bars]
    if missing and missing_policy == "reject":
        raise ValueError("Missing exchange sessions: " + ", ".join(map(str, missing)))
    retained = [day for day in expected if not missing or day > max(missing)]
    if len(retained) < 2:
        raise ValueError("Insufficient contiguous completed sessions")
    future = [s for s in schedule if s.closes_at > as_of][:horizon]
    if len(future) != horizon:
        raise ValueError("Exchange calendar does not cover requested forecast horizon")
    if len({a.id for a in actions}) != len(actions):
        raise ValueError("Duplicate corporate actions")
    if any(a.known_at > as_of for a in actions):
        raise ValueError("Corporate action was not known as of this research cutoff")
    if any(expected[-1] < a.effective_session <= future[-1].day for a in actions):
        raise ValueError("Forecast horizon crosses a corporate action; inverse adjustment required")
    active = [a for a in actions if min(bars) < a.effective_session <= expected[-1]]
    if any(a.effective_session not in completed for a in active):
        raise ValueError("Corporate action must fall on a known exchange session")
    if any(a.kind == "other" for a in active):
        raise ValueError("Unsupported corporate action")
    output = []
    applied: set[str] = set()
    for day in retained:
        bar = bars[day]
        price, volume = Decimal(1), Decimal(1)
        for action in active:
            if action.effective_session <= day:
                continue
            if action.kind == "split" and input_policy == "raw":
                assert action.split_ratio is not None
                price /= action.split_ratio
                volume *= action.split_ratio
                applied.add(action.id)
            if action.kind == "dividend" and input_policy != "total_return_adjusted":
                if action.price_factor is None:
                    raise ValueError("Dividend requires a documented historical price factor")
                price *= action.price_factor
                applied.add(action.id)
        output.append(
            Candle(
                session=day,
                open=bar.open * price,
                high=bar.high * price,
                low=bar.low * price,
                close=bar.close * price,
                volume=bar.volume * volume,
            )
        )
    # Amount is observed traded currency turnover, not adjusted close * volume.
    # Omit it for the whole context when adjustment occurred or coverage is partial.
    keep_amount = not applied and all(bars[day].amount is not None for day in retained)
    if keep_amount:
        output = [bar.model_copy(update={"amount": bars[bar.session].amount}) for bar in output]
    truncated = max(0, len(output) - max_context)
    output = output[-max_context:]
    return PreparedCandles(
        candles=output,
        historical_timestamps=[completed[b.session].closes_at.astimezone(zone) for b in output],
        future_timestamps=[s.closes_at.astimezone(zone) for s in future],
        timezone=timezone,
        currency=currency.upper(),
        provider=provider,
        calendar_source=calendar_source,
        as_of=as_of,
        adjustment_policy="total_return_adjusted_as_of",
        applied_actions=sorted(applied),
        missing_sessions=missing,
        truncated_count=truncated,
        amount_policy="observed_turnover" if keep_amount else "omitted",
        warnings=(
            ["Context starts after missing sessions; no candles were fabricated."]
            if missing
            else []
        )
        + (
            []
            if keep_amount
            else ["Amount omitted because coverage or adjustment basis is incompatible."]
        ),
    )
