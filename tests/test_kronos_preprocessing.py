from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from financial_ai.kronos.preprocessing import Candle, Session, CorporateAction, prepare_candles

NY = ZoneInfo("America/New_York")


def stamp(day):
    return datetime(2026, 9, day, 16, tzinfo=NY)


def bar(day, price, volume=100):
    return Candle(
        session=date(2026, 9, day), open=price, high=price, low=price, close=price, volume=volume
    )


def prepare(bars, **overrides):
    options = dict(
        sessions=[Session(day=stamp(d).date(), closes_at=stamp(d)) for d in [3, 4, 8, 9, 10, 11]],
        actions=[],
        as_of=stamp(9),
        timezone="America/New_York",
        currency="USD",
        provider="fixture",
        calendar_source="fixture-XNYS",
        input_policy="raw",
        actions_complete=True,
        horizon=2,
    )
    options.update(overrides)
    return prepare_candles(bars, **options)


def test_split_adjusts_all_prices_and_volume_without_holiday_candles():
    action = CorporateAction(
        id="split",
        kind="split",
        effective_session=date(2026, 9, 8),
        known_at=stamp(4),
        split_ratio=Decimal(2),
    )
    bars = [bar(3, 100), bar(4, 100), bar(8, 50, 200), bar(9, 50, 200)]
    result = prepare(bars, actions=[action])
    assert [b.close for b in result.candles] == [Decimal(50)] * 4
    assert [b.volume for b in result.candles] == [Decimal(200)] * 4
    assert bars[0].close == 100
    assert [t.day for t in result.historical_timestamps] == [3, 4, 8, 9]
    assert [t.day for t in result.future_timestamps] == [10, 11]
    before_holiday = prepare([bar(3, 100), bar(4, 100)], as_of=stamp(4))
    assert [t.day for t in before_holiday.future_timestamps] == [8, 9]
    adjusted = prepare(
        [bar(d, 50, 200) for d in [3, 4, 8, 9]], actions=[action], input_policy="split_adjusted"
    )
    assert adjusted.candles[0].close == 50 and not adjusted.applied_actions


def test_missing_session_reject_or_explicit_suffix_and_truncation():
    with pytest.raises(ValueError, match="Missing exchange"):
        prepare([bar(d, 50) for d in [3, 8, 9]])
    result = prepare([bar(d, 50) for d in [3, 8, 9]], missing_policy="contiguous_suffix")
    assert [b.session.day for b in result.candles] == [8, 9]
    assert result.missing_sessions == [date(2026, 9, 4)]
    assert prepare([bar(d, 50) for d in [3, 4, 8, 9]], max_context=2).truncated_count == 2


def test_dividend_requires_factor_and_future_action_blocks_forecast():
    action = CorporateAction(
        id="div", kind="dividend", effective_session=date(2026, 9, 8), known_at=stamp(4)
    )
    bars = [bar(3, 100), bar(4, 100), bar(8, 99), bar(9, 99)]
    with pytest.raises(ValueError, match="Dividend requires"):
        prepare(bars, actions=[action])
    adjusted = prepare(bars, actions=[action.model_copy(update={"price_factor": Decimal("0.99")})])
    assert all(b.close == 99 for b in adjusted.candles)
    with pytest.raises(ValueError, match="crosses a corporate action"):
        prepare(bars, actions=[action.model_copy(update={"effective_session": date(2026, 9, 10)})])


def test_invalid_prices_sessions_and_action_coverage_fail():
    with pytest.raises(ValueError):
        bar(3, "NaN")
    with pytest.raises(ValueError, match="coverage"):
        prepare([bar(d, 50) for d in [3, 4, 8, 9]], actions_complete=False)
    with pytest.raises(ValueError, match="closed, unknown"):
        prepare([bar(d, 50) for d in [3, 4, 7, 8, 9]])
    with pytest.raises(ValueError, match="duplicate candles"):
        prepare([bar(3, 50), bar(3, 50)])


def test_amount_is_not_invented_and_preserved_only_with_full_coverage():
    bars = [bar(d, 50).model_copy(update={"amount": Decimal(5000)}) for d in [3, 4, 8, 9]]
    assert prepare(bars).candles[0].amount == 5000
    bars[0] = bar(3, 50)
    assert all(b.amount is None for b in prepare(bars).candles)
