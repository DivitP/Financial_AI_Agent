"""Comparable financial windows and exact lineage from SEC, FMP, or Yahoo.

Whole datasets fall back; values from different providers are never spliced into
one period. SEC durations and accessions are matched before computing anything.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from financial_ai.data.http import HttpRequest, SharedHttpClient
from financial_ai.data.safe_transport import SafeTransport
from financial_ai.providers.legacy_live import finite, symbol
from financial_ai.storage.artifacts import FileSystemArtifactStore


@dataclass(frozen=True)
class Fact:
    value: float
    unit: str
    end: str
    start: str | None
    filed: str | None
    url: str
    evidence_id: str
    locator: str
    accession: str | None = None


@dataclass
class Window:
    end: str
    start: str | None
    kind: str
    facts: dict[str, Fact] = field(default_factory=dict)

    def value(self, name: str) -> float | None:
        fact = self.facts.get(name)
        return fact.value if fact else None


@dataclass
class FinancialHistory:
    provider: str
    currency: str
    retrieved_at: str
    annual: list[Window] = field(default_factory=list)
    interim: list[Window] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    issuer: str | None = None
    issuer_id: str | None = None
    filings: list[dict] = field(default_factory=list)


# Fixed concepts only, not issuer-defined dimensions or inferred segment totals.
SEC_TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "sbc": ("ShareBasedCompensation",),
    "shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "debt_noncurrent": ("LongTermDebtNoncurrent",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
}
INSTANT = {"cash", "debt_noncurrent", "assets", "liabilities"}
FMP_FIELDS = {
    "revenue": ("income", "revenue"),
    "operating_income": ("income", "operatingIncome"),
    "net_income": ("income", "netIncome"),
    "shares": ("income", "weightedAverageShsOutDil"),
    "ocf": ("cash", "operatingCashFlow"),
    "capex": ("cash", "capitalExpenditure"),
    "sbc": ("cash", "stockBasedCompensation"),
    "cash": ("balance", "cashAndCashEquivalents"),
    "assets": ("balance", "totalAssets"),
    "liabilities": ("balance", "totalLiabilities"),
    "debt_noncurrent": ("balance", "longTermDebt"),
}
YAHOO_TYPES = {
    "revenue": "annualTotalRevenue",
    "operating_income": "annualOperatingIncome",
    "net_income": "annualNetIncome",
    "ocf": "annualOperatingCashFlow",
    "capex": "annualCapitalExpenditure",
    "sbc": "annualStockBasedCompensation",
    "shares": "annualDilutedAverageShares",
    "cash": "annualCashAndCashEquivalents",
    "assets": "annualTotalAssets",
    "liabilities": "annualTotalLiabilitiesNetMinorityInterest",
    "debt_noncurrent": "annualLongTermDebt",
}


def day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def save_source(store, provider, url, retrieved, payload) -> str:
    return store.put_text(
        json.dumps(
            dict(provider=provider, url=url, retrieved_at=retrieved, payload=payload),
            sort_keys=True,
        ),
        category="source",
    )


def complete(history: FinancialHistory) -> bool:
    return (
        sum(
            all(k in w.facts for k in ("revenue", "net_income", "ocf", "capex"))
            for w in history.annual
        )
        >= 2
    )


def _sec_entries(payload, field, now):
    concepts = payload.get("facts", {}).get("us-gaap", {})
    unit = "shares" if field == "shares" else "USD"
    results = []
    for tag in SEC_TAGS[field]:
        for entry in concepts.get(tag, {}).get("units", {}).get(unit, []):
            end, filed, start = (
                day(entry.get("end")),
                day(entry.get("filed")),
                day(entry.get("start")),
            )
            if (
                not end
                or not filed
                or end > now
                or filed > now
                or not finite(entry.get("val"))
                or entry.get("form") not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}
                or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(entry.get("accn", "")))
            ):
                continue
            results.append((tag, entry, start, end, filed))
    return results


def normalize_sec(payload, retrieved_at, evidence_id, filings) -> FinancialHistory:
    now = datetime.fromisoformat(retrieved_at).date()
    pools = {name: _sec_entries(payload, name, now) for name in SEC_TAGS}
    history = FinancialHistory("SEC EDGAR", "USD", retrieved_at)
    durations = [
        e
        for e in pools["revenue"]
        if e[2] and 330 <= (e[3] - e[2]).days <= 380 and e[1]["form"] in {"10-K", "10-K/A"}
    ]
    ends = sorted({e[3] for e in durations})[-4:]
    anchors = [
        max((e for e in durations if e[3] == end), key=lambda e: (e[4], e[1]["accn"]))
        for end in ends
    ]
    annual_end = ends[-1] if ends else date.min
    # Cash-flow statements are cumulative YTD; match revenue/profit to that same
    # duration rather than combining a quarterly revenue with nine-month cash flow.
    interim = [
        e
        for e in pools["ocf"]
        if e[2]
        and e[3] > annual_end
        and 45 <= (e[3] - e[2]).days <= 310
        and e[1]["form"] in {"10-Q", "10-Q/A"}
    ]
    if interim:
        latest = max(interim, key=lambda e: (e[3], e[4], (e[3] - e[2]).days))
        length = (latest[3] - latest[2]).days
        prior = [
            e
            for e in pools["ocf"]
            if e[2]
            and e[1]["accn"] == latest[1]["accn"]
            and 330 <= (latest[3] - e[3]).days <= 400
            and abs((e[3] - e[2]).days - length) <= 8
        ]
        anchors += ([max(prior, key=lambda e: e[3])] if prior else []) + [latest]
    urls = {f["accessionNumber"]: f["url"] for f in filings}
    for anchor in anchors:
        _, entry, start, end, _ = anchor
        kind = "FY" if end in ends and entry["form"].startswith("10-K") else "YTD"
        window = Window(end.isoformat(), start.isoformat() if start else None, kind)
        for name, pool in pools.items():
            matches = [
                e
                for e in pool
                if e[1]["accn"] == entry["accn"]
                and e[3] == end
                and ((name in INSTANT and not e[2]) or (name not in INSTANT and e[2] == start))
            ]
            if not matches:
                continue
            tag, item, fact_start, _, filed = min(matches, key=lambda e: SEC_TAGS[name].index(e[0]))
            # Conflicting duplicate facts within an accession are not silently resolved.
            if len({e[1]["val"] for e in matches if e[0] == tag}) != 1:
                history.notices.append(f"Conflicting SEC {tag} values for {end}; excluded.")
                continue
            url = urls.get(
                item["accn"],
                f"https://www.sec.gov/Archives/edgar/data/{int(payload['cik'])}/{item['accn'].replace('-', '')}/",
            )
            window.facts[name] = Fact(
                float(item["val"]),
                "shares" if name == "shares" else "USD",
                end.isoformat(),
                fact_start.isoformat() if fact_start else None,
                filed.isoformat(),
                url,
                evidence_id,
                f"us-gaap:{tag}",
                item["accn"],
            )
        (history.annual if kind == "FY" else history.interim).append(window)
    history.interim.sort(key=lambda w: w.end)
    history.notices.append(
        "Latest available filing presentation; historical comparatives may reflect later amendments. Not point-in-time data."
    )
    return history


def _json(http, url):
    response = http.fetch(HttpRequest("sec", url))
    if response.status_code != 200:
        raise ValueError(f"SEC returned HTTP {response.status_code}")
    result = json.loads(response.body)
    if not isinstance(result, dict):
        raise ValueError("SEC returned an invalid object")
    return result


def collect_sec(ticker, settings, store, retrieved_at, profile, *, http=None):
    contact = settings.sec_user_agent
    if "@" not in contact:
        raise ValueError("SEC contact is not configured")
    http = http or SharedHttpClient(
        SafeTransport(["www.sec.gov", "data.sec.gov"]),
        user_agent=contact,
        max_response_bytes=20_000_000,
        timeout_seconds=15,
        max_retries=1,
        provider_concurrency=1,
    )
    hint = str(profile.get("cik", ""))
    if not hint.isdigit() or not 0 < int(hint) < 10**10:
        mapping_url = "https://www.sec.gov/files/company_tickers.json"
        mapping = _json(http, mapping_url)
        save_source(store, "SEC EDGAR", mapping_url, retrieved_at, mapping)
        known = [v for v in mapping.values() if isinstance(v, dict) and v.get("ticker") == ticker]
        if not known:
            raise ValueError("Requested ticker is not in the SEC issuer mapping")
        hint = str(known[0]["cik_str"])
    cik = hint.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    submissions = _json(http, url)
    if ticker not in submissions.get("tickers", []) or int(submissions.get("cik", 0)) != int(cik):
        raise ValueError(
            "SEC issuer does not list the requested ticker; share class was not substituted"
        )
    save_source(store, "SEC EDGAR", url, retrieved_at, submissions)
    recent = submissions.get("filings", {}).get("recent", {})
    filings = []
    for form, acc, filed, document in zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("filingDate", []),
        recent.get("primaryDocument", []),
    ):
        filing_day = day(filed)
        if (
            form in {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K"}
            and re.fullmatch(r"[A-Za-z0-9_.-]+", document)
            and re.fullmatch(r"\d{10}-\d{2}-\d{6}", acc)
            and filing_day
            and filing_day <= datetime.fromisoformat(retrieved_at).date()
        ):
            filings.append(
                dict(
                    form=form,
                    accessionNumber=acc,
                    filed=filed,
                    url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{document}",
                )
            )
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    payload = _json(http, url)
    if int(payload.get("cik", 0)) != int(cik):
        raise ValueError("SEC financial facts do not match the resolved issuer")
    evidence = save_source(store, "SEC EDGAR", url, retrieved_at, payload)
    history = normalize_sec(payload, retrieved_at, evidence, filings)
    history.issuer, history.issuer_id = submissions.get("name"), cik
    history.filings = filings[:5]
    return history


def normalize_fmp(records, store, retrieved_at):
    history = FinancialHistory("FMP", "", retrieved_at)
    evidence = {
        k: save_source(store, r.provider, r.url, r.retrieved_at, r.data) for k, r in records.items()
    }
    for row in sorted(records["income"].data, key=lambda r: str(r.get("date", "")))[-4:]:
        end, currency = day(row.get("date")), row.get("reportedCurrency")
        if (
            not end
            or end > datetime.fromisoformat(retrieved_at).date()
            or row.get("period") not in {"FY", "annual"}
            or not re.fullmatch(r"[A-Z]{3}", str(currency))
        ):
            continue
        if history.currency and history.currency != currency:
            history.notices.append(
                "Currency changed across annual periods; earlier periods excluded."
            )
            history.annual = []
        history.currency = currency
        window = Window(end.isoformat(), None, "FY")
        for name, (group, key) in FMP_FIELDS.items():
            record = records[group]
            matches = [
                r
                for r in record.data
                if r.get("date") == window.end and r.get("reportedCurrency") == currency
            ]
            if not matches or not finite(matches[0].get(key)):
                continue
            item = matches[0]
            window.facts[name] = Fact(
                float(item[key]),
                "shares" if name == "shares" else currency,
                window.end,
                None,
                item.get("filingDate"),
                record.url,
                evidence[group],
                key,
            )
        history.annual.append(window)
    history.notices.extend(r.issue for r in records.values() if r.issue)
    history.notices.append(
        "Provider annual statements; duration start and restatement status are not supplied."
    )
    return history


def collect_yahoo(ticker, provider, store):
    params = dict(
        type=",".join(YAHOO_TYPES.values()),
        period1=int((provider.now - timedelta(days=1900)).timestamp()),
        period2=int(provider.now.timestamp()),
    )
    url = f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}?{urlencode(params)}"
    record, body = provider._record("Yahoo Finance", url, url)
    history = FinancialHistory("Yahoo Finance", "", record.retrieved_at)
    if body is None:
        history.notices.append(record.issue or "Financial history unavailable")
        return history
    payload = json.loads(body)
    evidence = save_source(store, "Yahoo Finance", url, record.retrieved_at, payload)
    windows: dict[str, Window] = {}
    inverse = {v: k for k, v in YAHOO_TYPES.items()}
    for result in payload.get("timeseries", {}).get("result") or []:
        types = result.get("meta", {}).get("type", [])
        if (
            not types
            or types[0] not in inverse
            or ticker not in result.get("meta", {}).get("symbol", [])
        ):
            continue
        field_name = inverse[types[0]]
        for item in result.get(types[0], []):
            end, currency, value = (
                day(item.get("asOfDate")),
                item.get("currencyCode"),
                item.get("reportedValue", {}).get("raw"),
            )
            if (
                not end
                or end > provider.now.date()
                or item.get("periodType") != "12M"
                or not finite(value)
            ):
                continue
            if not re.fullmatch(r"[A-Z]{3}", str(currency)):
                continue
            if history.currency and currency != history.currency:
                history.notices.append(
                    "Mixed reporting currencies excluded from Yahoo financial history."
                )
                continue
            history.currency = currency
            window = windows.setdefault(end.isoformat(), Window(end.isoformat(), None, "FY"))
            window.facts[field_name] = Fact(
                float(value),
                "shares" if field_name == "shares" else currency,
                window.end,
                None,
                None,
                url,
                evidence,
                types[0],
            )
    history.annual = [windows[end] for end in sorted(windows)][-4:]
    history.notices.append(
        "Yahoo annual financials: filing dates, fiscal start dates and restatement history unavailable; not independently verified against filings."
    )
    return history


def collect_history(ticker, provider, store, profile):
    ticker = symbol(ticker)
    notices = []
    candidates = []
    if provider.settings.sec_user_agent:
        try:
            history = collect_sec(
                ticker, provider.settings, store, provider.now.isoformat(), profile
            )
            candidates.append(history)
            if complete(history):
                return history
            notices.append(
                "SEC annual coverage is incomplete; alternate financial datasets were checked."
            )
        except Exception:
            notices.append(
                "SEC issuer/filing collection unavailable; using a labeled provider fallback if possible."
            )
    else:
        notices.append(
            "SEC primary-source collection needs SEC_USER_AGENT with a real contact email."
        )
    requests = [
        ("income", "income-statement"),
        ("balance", "balance-sheet-statement"),
        ("cash", "cash-flow-statement"),
    ]
    with ThreadPoolExecutor(max_workers=min(2, provider.settings.provider_concurrency)) as pool:
        responses = list(pool.map(lambda pair: provider.fmp(pair[1], ticker, limit=4), requests))
    records = {pair[0]: record for pair, record in zip(requests, responses, strict=True)}
    fmp = normalize_fmp(records, store, provider.now.isoformat())
    candidates.append(fmp)
    if complete(fmp):
        fmp.notices = notices + fmp.notices
        return fmp
    notices += fmp.notices
    try:
        candidates.append(collect_yahoo(ticker, provider, store))
    except Exception:
        notices.append("Yahoo financial-history response unavailable or invalid.")
    selected = max(candidates, key=lambda h: sum(len(w.facts) for w in h.annual))
    selected.notices = list(dict.fromkeys(notices + selected.notices))
    return selected
