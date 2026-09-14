from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from financial_ai.analysis.backtest import (
    Action,
    Dataset,
    Decision,
    LeakageError,
    Price,
    TradingSession,
    WalkForwardConfig,
    walk_forward,
)

NY = ZoneInfo("America/New_York")


def dataset():
    # Labor Day and weekend are absent; no generic business-day extrapolation.
    days = [3, 4, 8, 9, 10, 11, 14, 15]
    sessions = tuple(
        TradingSession(
            available_at=datetime(2026, 1, 1, tzinfo=NY),
            day=date(2026, 9, d),
            opens_at=datetime(2026, 9, d, 9, 30, tzinfo=NY),
            closes_at=datetime(2026, 9, d, 16, tzinfo=NY),
        )
        for d in days
    )
    prices = tuple(
        Price(
            session=s.day,
            open=100,
            close=100,
            available_at=s.closes_at,
            evidence_id=f"price-{s.day.day}",
        )
        for s in sessions
    )
    return Dataset(
        symbol="TEST",
        provider="fixture",
        currency="USD",
        timezone=str(NY),
        calendar_source="fixture-XNYS",
        actions_complete=True,
        sessions=sessions,
        prices=prices,
    )


def long(view):
    return Decision(allocation=1, evidence_ids=(view.prices[-1].evidence_id,))


def test_windows_calendar_and_next_open_execution():
    for mode, sizes in [("rolling", [2, 2, 2]), ("expanding", [2, 4, 6])]:
        seen = []

        def strategy(view):
            seen.append(view)
            assert all(p.available_at <= view.as_of for p in view.prices)
            assert view.as_of < view.forecast_sessions[0].opens_at
            return long(view)

        result = walk_forward(
            dataset(), WalkForwardConfig(mode=mode, train_sessions=2, horizon=2), strategy
        )
        assert [len(v.prices) for v in seen] == sizes
        assert result["folds"][0]["entry_session"] == "2026-09-08"
        assert Decimal(result["net_return"]) == 0


def test_revisions_selected_as_of_not_latest_in_file():
    data = dataset()
    revised = data.prices[0].model_copy(
        update={
            "close": Decimal(200),
            "available_at": data.sessions[4].closes_at,
            "evidence_id": "restatement",
        }
    )
    data = data.model_copy(update={"prices": data.prices + (revised,)})
    result = walk_forward(
        data, WalkForwardConfig(mode="expanding", train_sessions=2, horizon=2), long
    )
    assert "restatement" not in result["folds"][0]["training_evidence"]
    assert "restatement" in result["folds"][2]["training_evidence"]


def test_explicit_leakage_failures():
    data = dataset()
    cfg = WalkForwardConfig(train_sessions=2, horizon=2)
    with pytest.raises(LeakageError, match="future or out-of-window"):
        walk_forward(data, cfg, lambda v: Decision(allocation=1, evidence_ids=("price-15",)))
    delayed = data.prices[1].model_copy(update={"available_at": data.sessions[2].closes_at})
    with pytest.raises(LeakageError, match="No point-in-time"):
        walk_forward(
            data.model_copy(update={"prices": (data.prices[0], delayed) + data.prices[2:]}),
            cfg,
            long,
        )
    with pytest.raises(LeakageError, match="Model training cutoff"):
        walk_forward(
            data,
            cfg.model_copy(update={"model_training_cutoff": data.sessions[-1].closes_at}),
            long,
        )
    with pytest.raises(ValueError, match="training cutoff"):
        WalkForwardConfig(strategy_kind="trained_model")
    with pytest.raises(LeakageError, match="execution open"):
        walk_forward(data, cfg.model_copy(update={"decision_delay_seconds": 4 * 86400}), long)
    payload = data.model_dump()
    payload["prices"][0]["available_at"] -= timedelta(hours=1)
    with pytest.raises(ValueError, match="before close"):
        Dataset.model_validate(payload)
    payload = data.model_dump()
    payload["prices"][0]["adjustment_policy"] = "future_adjusted"
    with pytest.raises(ValueError):
        Dataset.model_validate(payload)
    late_calendar = data.sessions[2].model_copy(update={"available_at": data.sessions[3].closes_at})
    with pytest.raises(LeakageError, match="calendar vintage"):
        walk_forward(
            data.model_copy(
                update={"sessions": data.sessions[:2] + (late_calendar,) + data.sessions[3:]}
            ),
            cfg,
            long,
        )


def test_costs_charged_on_both_fills_and_cash_strategy():
    cfg = WalkForwardConfig(
        train_sessions=2, horizon=6, fee_bps=100, slippage_bps=100, initial_cash=100
    )
    result = walk_forward(dataset(), cfg, long)
    expected = Decimal(100) / (Decimal(101) * Decimal("1.01")) * Decimal(99) * Decimal(".99")
    assert float(result["final_equity"]) == pytest.approx(float(expected))
    assert Decimal(result["folds"][0]["fees"]) > 0
    flat = walk_forward(
        dataset(), cfg, lambda v: Decision(allocation=0, evidence_ids=(v.prices[-1].evidence_id,))
    )
    assert Decimal(flat["net_return"]) == 0


def test_split_dividend_entitlement_and_unpaid_cash():
    data = dataset()
    prices = tuple(
        p.model_copy(update={"open": Decimal(49), "close": Decimal(49)})
        if p.session.day >= 9
        else p
        for p in data.prices
    )
    actions = (
        Action(
            evidence_id="split",
            session=date(2026, 9, 9),
            available_at=data.sessions[2].closes_at,
            kind="split",
            value=2,
        ),
        Action(
            evidence_id="dividend",
            session=date(2026, 9, 9),
            available_at=data.sessions[2].closes_at,
            kind="dividend",
            value=1,
            payable_session=date(2026, 9, 15),
        ),
    )
    result = walk_forward(
        data.model_copy(update={"prices": prices, "actions": actions}),
        WalkForwardConfig(train_sessions=2, horizon=2, initial_cash=100),
        long,
    )
    first = result["folds"][0]
    assert first["known_actions"] == []
    assert Decimal(first["final_equity"]) == 100
    assert Decimal(first["cash_after_exit"]) == 98
    assert Decimal(first["dividends_receivable"]) == 2
    assert Decimal(result["folds"][1]["dividends_paid"]) == 0
    assert Decimal(result["folds"][2]["dividends_paid"]) == 2
    assert Decimal(result["final_equity"]) == 100
    # Purchase at ex-date open must not receive a split or dividend entitlement.
    later = walk_forward(
        data.model_copy(update={"prices": prices, "actions": actions}),
        WalkForwardConfig(train_sessions=3, horizon=2, initial_cash=100),
        long,
    )
    assert Decimal(later["folds"][0]["dividend_accrual"]) == 0
    assert Decimal(later["final_equity"]) == 100


def test_missing_sessions_fail_and_future_outcomes_cannot_change_first_decision():
    data = dataset()
    cfg = WalkForwardConfig(train_sessions=2, horizon=2)
    with pytest.raises(ValueError, match="Missing trading session"):
        walk_forward(data.model_copy(update={"prices": data.prices[:-1]}), cfg, long)

    def strategy(v):
        return Decision(
            allocation=int(v.prices[-1].close > 99), evidence_ids=(v.prices[-1].evidence_id,)
        )

    original = walk_forward(data, cfg, strategy)
    changed = data.model_copy(
        update={
            "prices": data.prices[:2]
            + tuple(p.model_copy(update={"close": Decimal(50)}) for p in data.prices[2:])
        }
    )
    altered = walk_forward(changed, cfg, strategy)
    assert original["folds"][0]["decision"] == altered["folds"][0]["decision"]
    assert original["folds"][0]["net_return"] != altered["folds"][0]["net_return"]
