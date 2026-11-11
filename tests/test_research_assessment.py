"""Financial goldens: dated comparability, evidence lineage and valuation algebra."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import json

import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError

from financial_ai.analysis.research_assessment import (
    ValuationAssumptions,
    assess,
    comparable,
    measure,
    trailing_window,
)
from financial_ai.providers.financial_history import (
    Fact,
    FinancialHistory,
    Window,
    collect_history,
    collect_sec,
    collect_yahoo,
    normalize_fmp,
    normalize_sec,
    save_source,
    SEC_TAGS,
)
from financial_ai.providers.legacy_live import LegacyLiveProvider, LiveRecord
from financial_ai.data.http import HttpResponse
from financial_ai.reporting_assessment import render_assessment
from financial_ai.security import sanitized_markdown
from financial_ai.storage.artifacts import FileSystemArtifactStore
from settings import Settings

NOW = datetime(2026, 11, 11, tzinfo=UTC)
ANNUAL_ACC = "0001652044-26-000001"
INTERIM_ACC = "0001652044-26-000080"


def window(start, end, kind, values, accession=ANNUAL_ACC):
    return Window(
        end,
        start,
        kind,
        {
            key: Fact(
                value,
                "shares" if key == "shares" else "USD",
                end,
                start,
                "2026-11-01",
                "https://www.sec.gov/Archives/fixture.htm",
                "source_" + "a" * 64,
                key,
                accession,
            )
            for key, value in values.items()
        },
    )


def history():
    annual = window(
        "2025-01-01",
        "2025-12-31",
        "FY",
        dict(
            revenue=150,
            operating_income=30,
            net_income=30,
            ocf=50,
            capex=30,
            sbc=10,
            shares=10,
            cash=60,
            debt_noncurrent=20,
            assets=200,
            liabilities=80,
        ),
    )
    prior = window(
        "2025-01-01",
        "2025-09-30",
        "YTD",
        dict(revenue=100, operating_income=20, net_income=20, ocf=35, capex=25, sbc=8, shares=10),
        INTERIM_ACC,
    )
    current = window(
        "2026-01-01",
        "2026-09-30",
        "YTD",
        dict(
            revenue=130,
            operating_income=22,
            net_income=35,
            ocf=38,
            capex=50,
            sbc=12,
            shares=10.5,
            cash=55,
            debt_noncurrent=30,
            assets=220,
            liabilities=95,
        ),
        INTERIM_ACC,
    )
    older = window(
        "2024-01-01",
        "2024-12-31",
        "FY",
        dict(revenue=120, operating_income=20, net_income=20, ocf=40, capex=15, sbc=8, shares=10),
    )
    return FinancialHistory(
        "SEC EDGAR",
        "USD",
        NOW.isoformat(),
        [older, annual],
        [prior, current],
        issuer="Fixture Alphabet",
        issuer_id="0001652044",
    )


def market(cap=900, currency="USD", stamp=None) -> tuple[LiveRecord, LiveRecord]:
    quote = LiveRecord(
        "Yahoo Finance",
        "https://query1.finance.yahoo.com/quote/GOOG",
        NOW.isoformat(),
        [
            dict(
                price=90,
                currency=currency,
                timestamp=stamp if stamp is not None else NOW.timestamp(),
            )
        ],
    )
    profile = LiveRecord(
        "FMP",
        "https://financialmodelingprep.com/stable/profile?symbol=GOOG",
        NOW.isoformat(),
        [dict(symbol="GOOG", currency=currency, marketCap=cap, sector="Technology")],
    )
    return quote, profile


def sec_payload():
    h = history()
    payload: dict = {"cik": 1652044, "facts": {"us-gaap": {}}}
    for w in h.annual + h.interim:
        for key, fact in w.facts.items():
            tag = SEC_TAGS[key][0]
            entries = (
                payload["facts"]["us-gaap"]
                .setdefault(tag, {"units": {}})["units"]
                .setdefault(fact.unit, [])
            )
            row = dict(
                end=w.end,
                filed="2026-11-01",
                form="10-K" if w.kind == "FY" else "10-Q",
                accn=fact.accession,
                val=fact.value,
            )
            if key not in {"cash", "debt_noncurrent", "assets", "liabilities"}:
                row["start"] = w.start
            entries.append(row)
    return payload


def test_ttm_bridge_and_scenario_goldens_preserve_all_inputs():
    h = history()
    basis = trailing_window(h)
    assert basis is not None
    assert basis.kind == "TTM" and basis.start == "2025-10-01" and basis.end == "2026-09-30"
    assert basis.value("revenue") == 180
    assert basis.value("net_income") == 45
    assert basis.value("ocf") == 53
    assert basis.value("capex") == 55
    assert "shares" not in basis.facts and "cash" not in basis.facts
    result = assess(h, *market(), now=NOW)
    assert result.trajectory == "Mixed"
    assert result.metrics["revenue_growth"].value == pytest.approx(0.3)
    assert result.metrics["margin_change"].value == pytest.approx(22 / 130 - 0.2)
    assert result.metrics["basis_fcf"].value == -2
    assert len(result.metrics["basis_fcf"].facts) == 6
    assert result.valuation["price_to_earnings"].value == 20
    assert result.valuation["price_to_sales"].value == 5
    assert "price_to_fcf" not in result.valuation
    assert result.valuation["fcf_yield"].value == pytest.approx(-2 / 900)
    assert result.scenarios[1]["terminal"] == pytest.approx(45 * 1.1**3 * 25)
    assert result.implied_growth == pytest.approx(((900 * 1.1**3 / 25) / 45) ** (1 / 3) - 1)
    assert all(
        item.facts
        for item in result.positive + result.negative + result.observations + result.monitor
    )


def test_nonpositive_comparison_and_zero_denominators_are_not_growth_rates():
    h = history()
    h.interim[0].facts["ocf"] = replace(h.interim[0].facts["ocf"], value=20)
    h.interim[0].facts["revenue"] = replace(h.interim[0].facts["revenue"], value=0)
    result = assess(h, *market(), now=NOW)
    assert "revenue_growth" not in result.metrics
    assert measure(h.interim[0], "operating_margin") is None
    assert any("nonpositive base" in i.text for i in result.positive + result.negative)
    del h.interim[1].facts["net_income"]
    assert measure(h.interim[1], "cash_conversion") is None


@pytest.mark.parametrize("mismatch", ["duration", "gap", "currency", "missing"])
def test_invalid_ttm_bridges_do_not_mix_windows(mismatch):
    h = history()
    if mismatch == "duration":
        h.interim[-1].start = "2026-07-01"
    elif mismatch == "gap":
        h.interim[-1].start = "2026-01-03"
    elif mismatch == "currency":
        h.interim[-1].facts["net_income"] = replace(h.interim[-1].facts["net_income"], unit="EUR")
    else:
        del h.interim[-1].facts["net_income"]
    basis = trailing_window(h)
    assert basis is not None
    if mismatch in {"duration", "gap"}:
        assert basis.kind == "FY"
    else:
        assert basis.value("net_income") is None


@pytest.mark.parametrize(
    "change",
    [
        "no_cap",
        "currency",
        "no_time",
        "stale",
        "future",
        "invalid_time",
        "loss",
        "old_financials",
        "no_financials",
        "financial_sector",
    ],
)
def test_valuation_gates_do_not_invent_scenarios(change):
    h = history()
    q, p = market()
    if change == "no_cap":
        p.data[0]["marketCap"] = None
    elif change == "currency":
        p.data[0]["currency"] = q.data[0]["currency"] = "EUR"
    elif change == "no_time":
        q.data[0]["timestamp"] = None
    elif change == "stale":
        q.data[0]["timestamp"] -= 8 * 86400
    elif change == "future":
        q.data[0]["timestamp"] += 86400
    elif change == "invalid_time":
        q.data[0]["timestamp"] = 10**30
    elif change == "loss":
        for w in h.annual + h.interim:
            w.facts["net_income"] = replace(w.facts["net_income"], value=-10)
    elif change == "old_financials":
        h.interim = []
        h.annual = [window("2022-01-01", "2022-12-31", "FY", dict(revenue=100, net_income=10))]
    elif change == "no_financials":
        h.annual = h.interim = []
    else:
        p.data[0]["sector"] = "Financial Services"
    result = assess(h, q, p, now=NOW)
    assert not result.scenarios
    assert result.implied_growth is None
    assert result.limitations


def test_annual_fallback_and_one_period_remain_explicit():
    h = history()
    h.interim = []
    result = assess(h, *market(), now=NOW)
    assert result.basis is not None
    assert result.basis.kind == "FY"
    assert any("Annual-only" in note for note in result.limitations)
    assert result.scenarios
    h.annual = h.annual[-1:]
    assert assess(h, *market(), now=NOW).trajectory == "Insufficient evidence"
    assert not comparable(Window("2026-01-01", None, "FY"), Window("2023-01-01", None, "FY"))


@pytest.mark.parametrize(
    "options",
    [
        dict(years=0),
        dict(years=11),
        dict(years=2.5),
        dict(exit_multiple=0),
        dict(earnings_growth_pct=float("nan")),
        dict(target_equity_growth_pct=100),
        dict(probability=0.9),
    ],
)
def test_assumptions_reject_invalid_or_undocumented_inputs(options):
    with pytest.raises(ValidationError):
        ValuationAssumptions.model_validate(options)


def test_assumptions_change_calculations_without_changing_observations():
    a = assess(history(), *market(), now=NOW)
    b = assess(history(), *market(), ValuationAssumptions(years=5, exit_multiple=20), now=NOW)
    assert a.scenarios[1]["terminal"] != b.scenarios[1]["terminal"]
    assert a.metrics["revenue_growth"] == b.metrics["revenue_growth"]


def test_sec_normalization_matches_durations_units_and_accessions():
    payload = sec_payload()
    h = normalize_sec(payload, NOW.isoformat(), "source_fixture", [])
    assert len(h.annual) == 2 and len(h.interim) == 2
    assert h.annual[-1].facts["cash"].start is None
    assert h.interim[-1].value("revenue") == 130
    assert h.interim[-1].facts["revenue"].accession == INTERIM_ACC
    basis = trailing_window(h)
    assert basis is not None and basis.value("net_income") == 45
    assert "later amendments" in h.notices[0]


def test_sec_excludes_quarters_future_records_bad_units_and_conflicting_duplicates():
    payload = sec_payload()
    revenue = payload["facts"]["us-gaap"][SEC_TAGS["revenue"][0]]["units"]["USD"]
    last = deepcopy(revenue[-1])
    revenue += [
        dict(last, start="2026-07-01", val=99999),
        dict(last, filed="2030-01-01", val=99999),
        dict(last, accn="bad", val=99999),
        dict(last, val=float("nan")),
    ]
    payload["facts"]["us-gaap"][SEC_TAGS["revenue"][0]]["units"]["EUR"] = [dict(last, val=99999)]
    h = normalize_sec(payload, NOW.isoformat(), "fixture", [])
    assert h.interim[-1].value("revenue") == 130
    revenue.append(dict(last, val=999))
    h = normalize_sec(payload, NOW.isoformat(), "fixture", [])
    assert h.interim[-1].value("revenue") is None
    assert any("Conflicting" in note for note in h.notices)


class SecHttp:
    def __init__(self, *, wrong=False, status=200):
        self.wrong, self.status = wrong, status
        self.calls = []

    def fetch(self, request):
        self.calls.append(request.url)
        payload: dict
        if "company_tickers" in request.url:
            payload = {"0": dict(cik_str=1652044, ticker="GOOG", title="Fixture Alphabet")}
        elif "submissions" in request.url:
            payload = dict(
                cik=1652044,
                name="Fixture Alphabet",
                tickers=["WRONG"] if self.wrong else ["GOOG", "GOOGL"],
                filings=dict(
                    recent=dict(
                        form=["10-Q"],
                        accessionNumber=[INTERIM_ACC],
                        filingDate=["2026-11-01"],
                        primaryDocument=["goog.htm"],
                    )
                ),
            )
        else:
            payload = sec_payload()
        return HttpResponse(self.status, {}, json.dumps(payload).encode())


def test_sec_collector_resolves_share_classes_to_one_issuer_without_substituting_quotes(tmp_path):
    settings = Settings(_env_file=None, SEC_USER_AGENT="Fixture contact@example.test")
    store = FileSystemArtifactStore(tmp_path)
    client = SecHttp()
    h = collect_sec("GOOG", settings, store, NOW.isoformat(), {}, http=client)
    assert h.issuer_id == "0001652044" and h.issuer == "Fixture Alphabet"
    assert len(client.calls) == 3
    assert len(list(tmp_path.rglob("*.txt"))) == 3
    h = collect_sec("GOOGL", settings, store, NOW.isoformat(), dict(cik="1652044"), http=SecHttp())
    assert h.issuer_id == "0001652044"
    with pytest.raises(ValueError, match="share class was not substituted"):
        collect_sec(
            "GOOG", settings, store, NOW.isoformat(), dict(cik="1652044"), http=SecHttp(wrong=True)
        )
    with pytest.raises(ValueError, match="HTTP 403"):
        collect_sec("GOOG", settings, store, NOW.isoformat(), {}, http=SecHttp(status=403))
    settings.sec_user_agent = ""
    with pytest.raises(ValueError, match="not configured"):
        collect_sec("GOOG", settings, store, NOW.isoformat(), {}, http=SecHttp())


class YahooHttp:
    def __init__(self, payload):
        self.payload = payload

    def fetch(self, request):
        return HttpResponse(200, {}, json.dumps(self.payload).encode())


def test_yahoo_annual_fallback_retains_missing_filing_metadata_and_excludes_quarters(tmp_path):
    payload = dict(
        timeseries=dict(
            result=[
                dict(
                    meta=dict(type=["annualTotalRevenue"], symbol=["GOOG"]),
                    annualTotalRevenue=[
                        dict(
                            asOfDate="2025-12-31",
                            periodType="12M",
                            currencyCode="USD",
                            reportedValue=dict(raw=150),
                        ),
                        dict(
                            asOfDate="2026-09-30",
                            periodType="3M",
                            currencyCode="USD",
                            reportedValue=dict(raw=40),
                        ),
                    ],
                ),
                dict(
                    meta=dict(type=["annualOperatingCashFlow"]),
                    annualOperatingCashFlow=[
                        dict(
                            asOfDate="2025-12-31",
                            periodType="12M",
                            currencyCode="USD",
                            reportedValue=dict(raw=50),
                        )
                    ],
                ),
            ]
        )
    )
    provider = LegacyLiveProvider(Settings(_env_file=None), http=YahooHttp(payload), now=NOW)
    h = collect_yahoo("GOOG", provider, FileSystemArtifactStore(tmp_path))
    assert len(h.annual) == 1 and h.annual[0].value("revenue") == 150
    assert h.annual[0].facts["revenue"].filed is None
    assert "filing dates" in h.notices[0]


def test_fmp_comparability_missing_values_and_currency_changes(tmp_path):
    base = dict(
        symbol="GOOG",
        date="2025-12-31",
        period="FY",
        reportedCurrency="USD",
        revenue=150,
        netIncome=30,
        operatingIncome=25,
        filingDate="2026-02-01",
    )
    records = {
        k: LiveRecord("FMP", f"https://fmp.test/{k}", NOW.isoformat(), [deepcopy(base)])
        for k in ("income", "balance", "cash")
    }
    records["cash"].data[0].update(operatingCashFlow=50, capitalExpenditure=-30)
    h = normalize_fmp(records, FileSystemArtifactStore(tmp_path), NOW.isoformat())
    fcf = measure(h.annual[0], "fcf")
    assert fcf is not None and fcf.value == 20
    assert h.annual[0].facts["net_income"].filed == "2026-02-01"
    records["income"].data.insert(0, dict(base, date="2024-12-31", reportedCurrency="EUR"))
    h = normalize_fmp(records, FileSystemArtifactStore(tmp_path), NOW.isoformat())
    assert len(h.annual) == 1 and h.currency == "USD"
    assert any("Currency changed" in note for note in h.notices)


def test_report_leads_with_interpretation_and_cites_every_calculated_input():
    rendered = render_assessment(
        history(), *market(), {"quote": "source_quote", "profile": "source_profile"}, now=NOW
    )
    assert rendered.startswith("### Business trajectory: Mixed")
    assert "Expectations hurdle" in rendered and "TTM" in rendered
    assert "Bear illustration" in rendered and "Sensitivity" in rendered
    assert "not probabilities or price targets" in rendered
    assert "source_" in rendered and INTERIM_ACC in rendered
    page = BeautifulSoup(sanitized_markdown(rendered), "html.parser")
    assert len(page.select("table")) >= 5
    assert len(page.select("details li")) > 10
    assert "margin" in page.text and "Capital expenditure" in page.text
    assert "BUY" not in rendered and "SELL" not in rendered


def test_collection_prefers_complete_sec_and_never_splices_provider_facts(tmp_path, monkeypatch):
    h = history()
    provider = SimpleNamespace(
        settings=Settings(_env_file=None, SEC_USER_AGENT="Fixture contact@example.test"), now=NOW
    )
    monkeypatch.setattr("financial_ai.providers.financial_history.collect_sec", lambda *args: h)
    assert collect_history("GOOG", provider, FileSystemArtifactStore(tmp_path), {}) is h


def test_fmp_and_yahoo_fallbacks_are_complete_datasets_with_explicit_failures(
    tmp_path, monkeypatch
):
    def blocked(*args):
        raise ValueError("Private upstream failure")

    settings = Settings(_env_file=None, SEC_USER_AGENT="Fixture contact@example.test")
    provider = SimpleNamespace(settings=settings, now=NOW)
    records = [
        dict(
            symbol="GOOG",
            date=f"{year}-12-31",
            reportedCurrency="USD",
            period="FY",
            revenue=100,
            netIncome=10,
            operatingCashFlow=20,
            capitalExpenditure=-5,
        )
        for year in (2024, 2025)
    ]
    provider.fmp = lambda endpoint, ticker, limit: LiveRecord(
        "FMP", f"https://fmp.test/{endpoint}", NOW.isoformat(), records
    )
    monkeypatch.setattr("financial_ai.providers.financial_history.collect_sec", blocked)
    selected = collect_history("GOOG", provider, FileSystemArtifactStore(tmp_path), {})
    assert selected.provider == "FMP" and len(selected.annual) == 2
    assert any("SEC issuer" in n for n in selected.notices)
    provider.fmp = lambda endpoint, ticker, limit: LiveRecord(
        "FMP", f"https://fmp.test/{endpoint}", NOW.isoformat(), [], "HTTP 402 restricted"
    )
    alternate = history()
    alternate.provider = "Yahoo Finance"
    monkeypatch.setattr(
        "financial_ai.providers.financial_history.collect_yahoo", lambda *args: alternate
    )
    selected = collect_history("GOOG", provider, FileSystemArtifactStore(tmp_path), {})
    assert selected is alternate and any("402" in n for n in selected.notices)
    monkeypatch.setattr("financial_ai.providers.financial_history.collect_yahoo", blocked)
    selected = collect_history("GOOG", provider, FileSystemArtifactStore(tmp_path), {})
    assert not selected.annual and any("invalid" in n for n in selected.notices)


@pytest.mark.parametrize(
    ("factor", "label"), [(1.2, "Improving"), (0.8, "Weakening"), (1, "Stable")]
)
def test_trajectory_labels_describe_measured_changes_not_forecasts(factor, label):
    h = history()
    prior, current = h.interim
    for key in ("revenue", "operating_income", "ocf", "capex"):
        current.facts[key] = replace(current.facts[key], value=prior.facts[key].value)
    current.facts["revenue"] = replace(current.facts["revenue"], value=100 * factor)
    current.facts["operating_income"] = replace(
        current.facts["operating_income"], value=20 * factor * factor
    )
    current.facts["ocf"] = replace(current.facts["ocf"], value=25 + 10 * factor)
    result = assess(h, *market(), now=NOW)
    assert result.trajectory == label


def test_renderer_handles_insufficient_coverage_and_escapes_source_labels():
    h = history()
    h.annual = h.interim = []
    h.issuer = "<script>untrusted</script>"
    h.filings = [
        dict(form="10-Q", filed="2026-11-01", url="https://www.sec.gov/Archives/fixture.htm")
    ]
    rendered = sanitized_markdown(render_assessment(h, *market(), {}, now=NOW))
    assert "Insufficient evidence" in rendered and "No terminal values" in rendered
    assert "<script>" not in rendered
    assert "Recent original filings" in rendered
