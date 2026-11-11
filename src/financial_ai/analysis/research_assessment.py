"""Deterministic business assessment and assumption-driven issuer valuations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from financial_ai.providers.financial_history import Fact, FinancialHistory, Window, day
from financial_ai.providers.legacy_live import finite


class ValuationAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    years: int = Field(default=3, ge=1, le=10)
    earnings_growth_pct: float = Field(default=10, ge=-50, le=50)
    exit_multiple: float = Field(default=25, ge=6, le=80)
    target_equity_growth_pct: float = Field(default=10, ge=-20, le=30)


@dataclass(frozen=True)
class Measure:
    value: float
    unit: str
    facts: tuple[Fact, ...]


@dataclass(frozen=True)
class Insight:
    text: str
    facts: tuple[Fact, ...]


@dataclass
class Assessment:
    trajectory: str = "Insufficient evidence"
    comparison: str = "No comparable financial windows"
    positive: list[Insight] = field(default_factory=list)
    negative: list[Insight] = field(default_factory=list)
    observations: list[Insight] = field(default_factory=list)
    monitor: list[Insight] = field(default_factory=list)
    metrics: dict[str, Measure] = field(default_factory=dict)
    basis: Window | None = None
    valuation: dict[str, Measure] = field(default_factory=dict)
    scenarios: list[dict] = field(default_factory=list)
    sensitivity: list[dict] = field(default_factory=list)
    implied_growth: float | None = None
    market_cap: float | None = None
    market_source: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


def measure(window: Window, name: str) -> Measure | None:
    def direct(key):
        fact = window.facts.get(key)
        return Measure(fact.value, fact.unit, (fact,)) if fact else None

    if name == "fcf":
        ocf, capex = direct("ocf"), direct("capex")
        if ocf and capex and ocf.unit == capex.unit:
            return Measure(ocf.value - abs(capex.value), ocf.unit, ocf.facts + capex.facts)
        return None
    ratios = {
        "operating_margin": ("operating_income", "revenue"),
        "fcf_margin": ("fcf", "revenue"),
        "capex_intensity": ("capex", "revenue"),
        "cash_conversion": ("ocf", "net_income"),
        "sbc_revenue": ("sbc", "revenue"),
    }
    if name in ratios:
        numerator, denominator = (measure(window, k) for k in ratios[name])
        if (
            numerator
            and denominator
            and numerator.unit == denominator.unit
            and denominator.value > 0
        ):
            value = abs(numerator.value) if name == "capex_intensity" else numerator.value
            return Measure(
                value / denominator.value, "fraction", numerator.facts + denominator.facts
            )
        return None
    return direct(name)


def comparable(current: Window, previous: Window) -> bool:
    current_end, prior_end = day(current.end), day(previous.end)
    if (
        not current_end
        or not prior_end
        or current.kind != previous.kind
        or not 330 <= (current_end - prior_end).days <= 400
    ):
        return False
    if current.start and previous.start:
        current_start, prior_start = day(current.start), day(previous.start)
        if (
            not current_start
            or not prior_start
            or abs((current_end - current_start).days - (prior_end - prior_start).days) > 8
        ):
            return False
    return True


def trailing_window(history: FinancialHistory) -> Window | None:
    if not history.annual:
        return None
    annual = history.annual[-1]
    if len(history.interim) != 2:
        return annual
    prior, current = history.interim
    annual_end, prior_end = day(annual.end), day(prior.end)
    # A valid TTM bridge is FY + this year's YTD - last year's same YTD.
    # Do not add share averages, balance-sheet instants, EPS or incompatible periods.
    if (
        not comparable(current, prior)
        or not current.start
        or not prior.start
        or not annual.start
        or prior.start != annual.start
        or annual_end is None
        or prior_end is None
        or day(current.start) != annual_end + timedelta(days=1)
    ):
        return annual
    window = Window(current.end, (prior_end + timedelta(days=1)).isoformat(), "TTM")
    for key in ("revenue", "operating_income", "net_income", "ocf", "capex", "sbc"):
        facts = [w.facts.get(key) for w in (annual, current, prior)]
        a, c, p = facts
        if a is None or c is None or p is None:
            continue
        if a.unit != c.unit or a.unit != p.unit:
            continue
        # Preserve all input references on the derived value (see _trailing_refs).
        window.facts[key] = Fact(
            a.value + c.value - p.value,
            a.unit,
            current.end,
            window.start,
            c.filed,
            c.url,
            c.evidence_id,
            f"TTM bridge: {a.locator} + {c.locator} - {p.locator}",
            c.accession,
        )
    return window


def _trailing_refs(history, key):
    return tuple(w.facts[key] for w in [history.annual[-1], *history.interim] if key in w.facts)


def _pair(history):
    if len(history.interim) == 2 and comparable(history.interim[-1], history.interim[-2]):
        return history.interim[-1], history.interim[-2]
    if len(history.annual) >= 2 and comparable(history.annual[-1], history.annual[-2]):
        return history.annual[-1], history.annual[-2]
    return None


def assess(history: FinancialHistory, quote, profile, assumptions=None, *, now=None) -> Assessment:
    assumptions = assumptions or ValuationAssumptions()
    now = now or datetime.now(UTC)
    result = Assessment()
    profile_row = profile.data[0] if profile.data else {}
    sector = str(profile_row.get("sector", "")).casefold()
    if (
        any(s in sector for s in ("financial", "real estate"))
        or profile_row.get("isEtf") is True
        or profile_row.get("isFund") is True
    ):
        result.limitations.append(
            "The generic corporate cash-flow assessment and earnings scenarios are not applicable to financial companies, real-estate entities or funds; specialist analysis is required."
        )
        return result
    pair = _pair(history)
    directions = []
    if pair:
        current, previous = pair
        result.comparison = f"{current.kind} ending {current.end} versus {previous.end}"
        for key, label in (
            ("revenue", "Revenue"),
            ("operating_margin", "Operating margin"),
            ("fcf", "Free cash flow"),
        ):
            latest, prior = measure(current, key), measure(previous, key)
            if not latest or not prior or latest.unit != prior.unit:
                continue
            change = latest.value - prior.value
            facts = latest.facts + prior.facts
            if key == "operating_margin":
                phrase = f"Operating margin moved from {prior.value:.1%} to {latest.value:.1%} ({change * 100:+.1f} percentage points)."
                result.metrics["margin_change"] = Measure(change, "fraction", facts)
            elif prior.value > 0:
                growth = change / prior.value
                result.metrics[key + "_growth"] = Measure(growth, "fraction", facts)
                phrase = f"{label} changed {growth:+.1%} year over year."
            else:
                phrase = f"{label} moved from {history.currency} {prior.value:,.0f} to {history.currency} {latest.value:,.0f}; percentage growth is not meaningful from a nonpositive base."
            insight = Insight(phrase, facts)
            if change > 0:
                result.positive.append(insight)
                directions.append(1)
            elif change < 0:
                result.negative.append(insight)
                directions.append(-1)
            else:
                result.observations.append(insight)
                directions.append(0)
            result.monitor.append(
                Insight(
                    f"Recheck {label.lower()} in the next comparable filing; a reversal of this change would alter the historical trend assessment.",
                    facts,
                )
            )
        if len(directions) >= 2:
            result.trajectory = (
                "Mixed"
                if 1 in directions and -1 in directions
                else "Improving"
                if 1 in directions
                else "Weakening"
                if -1 in directions
                else "Stable"
            )
        # Cash spending, cash conversion and dilution explain why earnings alone
        # need not establish a stronger business or a cheaper stock.
        for key in ("cash_conversion", "capex_intensity", "sbc_revenue"):
            value = measure(current, key)
            if not value:
                continue
            result.metrics[key] = value
            if key == "cash_conversion":
                observation = Insight(
                    f"Operating cash flow was {value.value:.2f}x reported net income; this is cash conversion, not a normalized-earnings estimate.",
                    value.facts,
                )
                (result.negative if value.value < 1 else result.observations).append(observation)
            elif key == "sbc_revenue":
                result.observations.append(
                    Insight(
                        f"Stock-based compensation was {value.value:.1%} of revenue. Reported free cash flow does not deduct this noncash compensation expense.",
                        value.facts,
                    )
                )
            else:
                old = measure(previous, key)
                if old:
                    observation = Insight(
                        f"Capital expenditure consumed {value.value:.1%} of revenue versus {old.value:.1%} in the comparison period. Check whether that spending translates into future operating cash flow.",
                        value.facts + old.facts,
                    )
                    (result.negative if value.value > old.value else result.observations).append(
                        observation
                    )
        shares, old_shares = measure(current, "shares"), measure(previous, "shares")
        income, operating = measure(current, "net_income"), measure(current, "operating_income")
        if income and operating and income.value > operating.value > 0:
            result.negative.append(
                Insight(
                    "Reported net income exceeded operating profit. Inspect nonoperating and tax items before treating reported earnings as a sustainable operating run rate.",
                    income.facts + operating.facts,
                )
            )
        if shares and old_shares and old_shares.value > 0:
            # For SEC, require the same comparative accession so a share split
            # cannot look like dilution by combining different presentations.
            if shares.facts[0].accession == old_shares.facts[0].accession:
                growth = shares.value / old_shares.value - 1
                result.observations.append(
                    Insight(
                        f"Weighted-average diluted shares changed {growth:+.1%} in comparable periods; share-count changes affect per-share outcomes.",
                        shares.facts + old_shares.facts,
                    )
                )
    basis = trailing_window(history)
    result.basis = basis
    if basis is None:
        result.limitations.append(
            "No usable annual financial baseline; an investment assessment cannot be completed."
        )
        return result
    if (now.date() - date.fromisoformat(basis.end)).days > 550:
        result.trajectory = "Insufficient evidence"
        result.limitations.append(
            "Financial baseline is more than 550 days old; valuation scenarios are withheld."
        )
        return result
    if basis.kind != "TTM":
        result.limitations.append(
            f"Annual-only valuation baseline ending {basis.end}; subsequent quarterly performance is not captured."
        )
    # Restore all underlying evidence references for TTM-derived measures.
    for key in ("revenue", "net_income", "ocf", "capex", "fcf"):
        value = measure(basis, key)
        if value:
            if basis.kind == "TTM":
                keys = ("ocf", "capex") if key == "fcf" else (key,)
                value = Measure(
                    value.value,
                    value.unit,
                    tuple(f for k in keys for f in _trailing_refs(history, k)),
                )
            result.metrics["basis_" + key] = value
    quote_row = quote.data[0] if quote.data else {}
    profile_row = profile.data[0] if profile.data else {}
    qcap, pcap = quote_row.get("marketCap"), profile_row.get("marketCap")
    market_cap = qcap if finite(qcap, positive=True) else pcap
    if not finite(market_cap, positive=True):
        result.limitations.append(
            "Issuer market capitalization is unavailable; valuation and scenario comparisons are withheld."
        )
        return result
    assert market_cap is not None
    market_cap = float(market_cap)
    currency = quote_row.get("currency") or profile_row.get("currency")
    if currency != history.currency:
        result.limitations.append(
            "Market and financial reporting currencies do not match; valuation is withheld without an FX observation."
        )
        return result
    if not finite(quote_row.get("timestamp"), positive=True):
        result.limitations.append(
            "Quote observation time is unavailable; valuation scenarios are withheld."
        )
        return result
    try:
        quote_time = datetime.fromtimestamp(quote_row["timestamp"], UTC)
    except (ValueError, OverflowError, OSError):
        result.limitations.append(
            "Quote observation time is invalid; valuation scenarios are withheld."
        )
        return result
    if (now - quote_time).total_seconds() > 7 * 86400 or quote_time > now + timedelta(minutes=5):
        result.limitations.append(
            "Quote is stale or future-dated; valuation scenarios are withheld."
        )
        return result
    result.market_cap = market_cap
    source = quote if finite(qcap, positive=True) else profile
    result.market_source = dict(
        url=source.url, provider=source.provider, retrieved_at=source.retrieved_at
    )
    result.limitations.append(
        "Valuation uses provider-reported issuer market capitalization, with no class-specific share-price target. Market-cap observation time may be unavailable even when the quote is dated."
    )
    for key, name in (
        ("net_income", "price_to_earnings"),
        ("revenue", "price_to_sales"),
        ("fcf", "price_to_fcf"),
    ):
        value = result.metrics.get("basis_" + key)
        if value and value.value > 0:
            result.valuation[name] = Measure(market_cap / value.value, "multiple", value.facts)
    fcf = result.metrics.get("basis_fcf")
    if fcf:
        result.valuation["fcf_yield"] = Measure(fcf.value / market_cap, "fraction", fcf.facts)
        if fcf.value <= 0:
            result.negative.append(
                Insight(
                    "Free cash flow over the valuation window is nonpositive. An earnings-based scenario does not establish cash support for that valuation.",
                    fcf.facts,
                )
            )
    earnings = result.metrics.get("basis_net_income")
    if not earnings or earnings.value <= 0:
        result.limitations.append(
            "Positive reported earnings are required for this earnings-multiple scenario model."
        )
        return result
    n, m, g, r = (
        assumptions.years,
        assumptions.exit_multiple,
        assumptions.earnings_growth_pct / 100,
        assumptions.target_equity_growth_pct / 100,
    )
    result.implied_growth = ((market_cap * (1 + r) ** n / m) / earnings.value) ** (1 / n) - 1
    for name, growth, multiple in (
        ("Bear illustration", g - 0.10, m - 5),
        ("Base illustration", g, m),
        ("Bull illustration", g + 0.10, m + 5),
    ):
        terminal = earnings.value * (1 + growth) ** n * multiple
        result.scenarios.append(
            dict(
                name=name,
                growth=growth,
                multiple=multiple,
                terminal=terminal,
                change=terminal / market_cap - 1,
                annualized=(terminal / market_cap) ** (1 / n) - 1,
            )
        )
    result.sensitivity = [
        dict(
            growth=growth,
            values=[earnings.value * (1 + growth) ** n * mult for mult in (m - 5, m, m + 5)],
        )
        for growth in (g - 0.10, g, g + 0.10)
    ]
    return result
