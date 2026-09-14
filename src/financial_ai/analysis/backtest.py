"""Single-instrument, non-overlapping walk-forward evaluation with as-of views."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class LeakageError(ValueError):
    """A requested observation or claim was unavailable at the decision cutoff."""


class Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True
    )


class TradingSession(Record):
    day: date
    available_at: AwareDatetime
    opens_at: AwareDatetime
    closes_at: AwareDatetime


class Price(Record):
    session: date
    open: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    available_at: AwareDatetime
    evidence_id: str = Field(min_length=1)
    adjustment_policy: Literal["raw"] = "raw"


class Action(Record):
    evidence_id: str = Field(min_length=1)
    session: date
    available_at: AwareDatetime
    kind: Literal["split", "dividend"]
    value: Decimal = Field(gt=0)  # new/old shares or cash per post-split share
    payable_session: date | None = None

    @model_validator(mode="after")
    def payment_date(self):
        if self.kind == "dividend" and (
            self.payable_session is None or self.payable_session < self.session
        ):
            raise ValueError("Dividend requires a payment date on/after its ex-date")
        if self.kind == "split" and self.payable_session is not None:
            raise ValueError("Split has no dividend payment date")
        return self


class WalkForwardConfig(Record):
    strategy_version: str = Field(default="unversioned-callback", min_length=1)
    mode: Literal["rolling", "expanding"] = "rolling"
    train_sessions: int = Field(default=60, ge=2)
    horizon: int = Field(default=5, ge=1)
    decision_delay_seconds: int = Field(default=0, ge=0)
    initial_cash: Decimal = Field(default=10000, gt=0)
    fee_bps: Decimal = Field(default=0, ge=0, lt=10000)
    slippage_bps: Decimal = Field(default=0, ge=0, lt=10000)
    model_training_cutoff: AwareDatetime | None = None
    strategy_kind: Literal["deterministic", "trained_model"] = "deterministic"

    @model_validator(mode="after")
    def training_metadata(self):
        if self.strategy_kind == "trained_model" and self.model_training_cutoff is None:
            raise LeakageError("Trained models require an auditable training cutoff")
        return self


class Snapshot(Record):
    as_of: AwareDatetime
    prices: tuple[Price, ...]
    actions: tuple[Action, ...]
    forecast_sessions: tuple[TradingSession, ...]


class Decision(Record):
    allocation: Decimal = Field(ge=0, le=1)  # long-only, remainder stays cash
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class Dataset(Record):
    symbol: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str
    calendar_source: str = Field(min_length=1)
    actions_complete: Literal[True]
    sessions: tuple[TradingSession, ...]
    prices: tuple[Price, ...]
    actions: tuple[Action, ...] = ()

    @model_validator(mode="after")
    def validate_history(self):
        zone = ZoneInfo(self.timezone)
        schedule = {s.day: s for s in self.sessions}
        if len(schedule) != len(self.sessions) or not self.sessions:
            raise ValueError("Empty or duplicate calendar")
        for s in self.sessions:
            if not s.opens_at < s.closes_at or any(
                t.astimezone(zone).date() != s.day for t in [s.opens_at, s.closes_at]
            ):
                raise ValueError("Invalid exchange-local session times")
        if any(a.closes_at >= b.opens_at for a, b in zip(self.sessions, self.sessions[1:])):
            raise ValueError("Calendar must be strictly ordered")
        ids = [p.evidence_id for p in self.prices] + [a.evidence_id for a in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate evidence IDs")
        versions = set()
        for p in self.prices:
            if p.session not in schedule:
                raise ValueError("Price outside supplied trading calendar")
            if p.available_at < schedule[p.session].closes_at:
                raise LeakageError("Full-session price marked available before close")
            key = (p.session, p.available_at)
            if key in versions:
                raise ValueError("Ambiguous price revisions")
            versions.add(key)
        if any(a.session not in schedule for a in self.actions):
            raise ValueError("Action outside supplied trading calendar")
        if len({(a.session, a.kind) for a in self.actions}) != len(self.actions):
            raise ValueError("Combine same-session actions explicitly; ambiguous action history")
        return self


def walk_forward(
    data: Dataset, config: WalkForwardConfig, strategy: Callable[[Snapshot], Decision]
) -> dict:
    """Refit inside strategy on each immutable snapshot; execution starts next open."""
    if len(data.sessions) < config.train_sessions + config.horizon:
        raise ValueError("Insufficient calendar for a complete fold")
    versions = {
        s.day: sorted([p for p in data.prices if p.session == s.day], key=lambda p: p.available_at)
        for s in data.sessions
    }
    if any(not values for values in versions.values()):
        raise ValueError("Missing trading session prices; no filling is allowed")
    equity = config.initial_cash
    cash = equity
    receivables: list[tuple[date, Decimal]] = []
    folds = []
    fee, slip = config.fee_bps / 10000, config.slippage_bps / 10000
    for end in range(
        config.train_sessions - 1, len(data.sessions) - config.horizon, config.horizon
    ):
        cutoff = data.sessions[end].closes_at + timedelta(seconds=config.decision_delay_seconds)
        future = data.sessions[end + 1 : end + 1 + config.horizon]
        if cutoff >= future[0].opens_at:
            raise LeakageError("Decision cutoff must precede execution open")
        if any(s.available_at > cutoff for s in data.sessions[: end + config.horizon + 1]):
            raise LeakageError("Trading calendar vintage was unavailable at decision time")
        if config.model_training_cutoff is not None and config.model_training_cutoff > cutoff:
            raise LeakageError("Model training cutoff is later than the decision")
        start = 0 if config.mode == "expanding" else end + 1 - config.train_sessions
        history = []
        for session in data.sessions[start : end + 1]:
            eligible = [p for p in versions[session.day] if p.available_at <= cutoff]
            if not eligible:
                raise LeakageError(f"No point-in-time price for {session.day}")
            history.append(eligible[-1])
        known = tuple(a for a in data.actions if a.available_at <= cutoff)
        # Raw prices remain raw; expose known actions, never future-adjust history.
        snapshot = Snapshot(
            as_of=cutoff, prices=tuple(history), actions=known, forecast_sessions=future
        )
        decision = Decision.model_validate(strategy(snapshot))
        allowed = {p.evidence_id for p in history} | {a.evidence_id for a in known}
        if not set(decision.evidence_ids) <= allowed:
            raise LeakageError("Decision cites future or out-of-window evidence")
        # Outcomes are isolated from the strategy and use the first published vintage.
        entry, exit_price = versions[future[0].day][0], versions[future[-1].day][0]
        budget = cash * decision.allocation
        fill = entry.open * (1 + slip)
        shares = budget / (fill * (1 + fee))
        entry_fee = shares * fill * fee
        slippage = shares * entry.open * slip
        dividends = Decimal(0)
        applied = []
        for session in future[1:]:  # entrant at ex-date open has no prior entitlement
            for action in sorted(data.actions, key=lambda a: a.kind != "split"):
                if action.session != session.day:
                    continue
                if action.kind == "split":
                    shares *= action.value
                else:
                    amount = shares * action.value
                    dividends += amount
                    assert action.payable_session is not None
                    receivables.append((action.payable_session, amount))
                applied.append(action.evidence_id)
        proceeds = shares * exit_price.close * (1 - slip)
        exit_fee = proceeds * fee
        slippage += shares * exit_price.close * slip
        payments = sum(
            (amount for day, amount in receivables if day <= exit_price.session), Decimal(0)
        )
        receivables = [(day, amount) for day, amount in receivables if day > exit_price.session]
        cash = cash - budget + proceeds - exit_fee + payments
        final = cash + sum((amount for _, amount in receivables), Decimal(0))
        folds.append(
            {
                "as_of": cutoff.isoformat(),
                "entry_session": entry.session.isoformat(),
                "exit_session": exit_price.session.isoformat(),
                "training_evidence": [p.evidence_id for p in history],
                "known_actions": [a.evidence_id for a in known],
                "decision": decision.model_dump(mode="json"),
                "outcome_evidence": [entry.evidence_id, exit_price.evidence_id] + applied,
                "initial_equity": str(equity),
                "final_equity": str(final),
                "net_return": str(final / equity - 1),
                "fees": str(entry_fee + exit_fee),
                "traded_notional": str(budget / (1 + fee) + proceeds),
                "slippage_cost": str(slippage),
                "dividend_accrual": str(dividends),
                "dividends_paid": str(payments),
                "cash_after_exit": str(cash),
                "dividends_receivable": str(final - cash),
            }
        )
        equity = final
    return {
        "symbol": data.symbol,
        "provider": data.provider,
        "currency": data.currency,
        "timezone": data.timezone,
        "calendar_source": data.calendar_source,
        "adjustment_policy": "raw; explicit split shares and dividend accrual",
        "config": config.model_dump(mode="json"),
        "folds": folds,
        "final_equity": str(equity),
        "net_return": str(equity / config.initial_cash - 1),
        "unused_tail_sessions": (len(data.sessions) - config.train_sessions) % config.horizon,
        "warnings": [
            "Research simulation, not calibrated forecast confidence or investment advice.",
            "Requires a complete point-in-time calendar, action history and instrument universe.",
        ],
    }
