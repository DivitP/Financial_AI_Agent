"""Source-backed reports for the Flask compatibility UI, without invented prose."""

from __future__ import annotations

import html
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from financial_ai.providers.legacy_live import LegacyLiveProvider, LiveRecord, finite, symbol
from financial_ai.storage.artifacts import FileSystemArtifactStore


def text(value) -> str:
    if value is None or value == "":
        return "Unavailable"
    value = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
    for character in ("\\", "|", "[", "]", "*", "_", "`"):
        value = value.replace(character, "\\" + character)
    return value


def number(value) -> str:
    return f"{value:,.2f}" if finite(value) else "Unavailable"


def timestamp(value) -> str:
    if not finite(value, positive=True):
        return "Unavailable"
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return "Unavailable"


def source_note(record: LiveRecord, artifact: str) -> str:
    retrieved = datetime.fromisoformat(record.retrieved_at).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"Source: [{text(record.provider)} dataset]({record.url}) · "
        f"Retrieved: {retrieved}.\n\n"
        f"<details><summary>Evidence record</summary><p><code>{artifact}</code></p></details>"
    )


def build_live_research(
    ticker: str, persist_dir: str, *, provider=None, settings=None, assumptions=None
):
    """Collect independent sources once, retain exact records, then render facts.

    Raw responses remain local; source text never contains credentials. The source
    snapshot, rather than an LLM's memory or a cached old report, supplies values.
    """
    from settings import get_settings
    from financial_ai.providers.financial_history import collect_history
    from financial_ai.analysis.research_assessment import ValuationAssumptions
    from financial_ai.reporting_assessment import render_assessment

    ticker = symbol(ticker)
    provider = provider or LegacyLiveProvider(settings or get_settings())
    calls = {
        "quote": lambda: provider.quote(ticker),
        "profile": lambda: provider.fmp("profile", ticker),
    }
    # SharedHttpClient deliberately rejects excess concurrent requests rather
    # than queueing them. Do not over-dispatch this request-scoped collector.
    with ThreadPoolExecutor(max_workers=min(2, provider.settings.provider_concurrency)) as pool:
        records = dict(zip(calls, pool.map(lambda fn: fn(), calls.values()), strict=True))
    profile_data = records["profile"].data
    company_name = profile_data[0].get("companyName") if profile_data else None
    store = FileSystemArtifactStore(Path(persist_dir) / "legacy_evidence")
    history = collect_history(ticker, provider, store, profile_data[0] if profile_data else {})
    records["news"] = provider.news(ticker, company_name=company_name)
    artifacts = {
        name: store.put_text(json.dumps(asdict(record), sort_keys=True), category="source")
        for name, record in records.items()
    }
    quote, profile = records["quote"], records["profile"]
    q = quote.data[0] if quote.data else {}
    p = profile.data[0] if profile.data else {}
    currency = text(q.get("currency") or p.get("currency"))
    market_cap = (
        q.get("marketCap") if finite(q.get("marketCap"), positive=True) else p.get("marketCap")
    )
    lines = [
        f"### {text(p.get('companyName') or q.get('name') or ticker)} ({ticker})",
        "",
        "A source-backed snapshot of company financials and recent headlines. For research and education.",
        "",
        "### Market snapshot",
        "",
        source_note(quote, artifacts["quote"]),
        "",
        f"Observation as of: {timestamp(q.get('timestamp'))}. Quotes may be delayed. "
        "Adjustment: provider quote as supplied, not a total-return series.",
        "",
        "| Observation | Value | Currency / unit |",
        "| --- | ---: | --- |",
        f"| Price | {number(q.get('price'))} | {currency} / share |",
        f"| Market capitalization | {number(market_cap)} | {currency} |",
        f"| Trading volume | {number(q.get('volume'))} | shares |",
        "",
    ]
    if quote.issue:
        lines += [text(quote.issue), ""]
    if not finite(q.get("marketCap"), positive=True) and finite(p.get("marketCap"), positive=True):
        lines += [
            f"Market capitalization uses the [profile snapshot]({profile.url}); its observation time is not supplied.",
            "",
        ]
    lines += [
        "### Company profile",
        "",
        source_note(profile, artifacts["profile"]),
        "",
        "Profile as-of time unavailable; this is a retrieved provider snapshot, not a current filing. "
        "Currency/unit/adjustment: not applicable to categorical profile fields.",
        "",
        "| Field | Provider-reported value |",
        "| --- | --- |",
    ]
    for key, label in (("sector", "Sector"), ("industry", "Industry"), ("exchange", "Exchange")):
        lines.append(f"| {label} | {text(p.get(key))} |")
    lines.append("")
    if profile.issue:
        lines += [text(profile.issue), ""]
    notices = [
        notice for r in records.values() for notice in ([r.issue] if r.issue else []) + r.notices
    ]
    lines += [
        "### Coverage and limitations",
        "",
        "Analyst consensus, industry benchmarks and full filing text were not collected. "
        "Financial trends, calculation inputs and assumption-driven scenarios appear in the assessment above.",
        "",
    ]
    lines += [f"- {text(notice)}" for notice in dict.fromkeys(notices)]
    news = records["news"]
    news_lines = [
        "### Recent headlines",
        "",
        source_note(news, artifacts["news"]),
        "",
        "Discovery only: headlines and publication metadata, not verified article bodies "
        "or a sentiment conclusion. Feed results can include related companies. "
        "Check publication dates; retrieval time does not establish freshness.",
        "",
    ]
    for article in news.data:
        # The collector has validated URLs. Do not execute or fetch linked content here.
        news_lines += [
            f"- [{text(article['title'])}]({article['url']}) — "
            f"published {text(article.get('publishedDate'))}."
        ]
    if not news.data:
        news_lines += [text(news.issue)]
    news_lines += ["", *[f"- Source fallback: {text(n)}" for n in news.notices]]
    assumptions = assumptions or ValuationAssumptions()
    store.put_text(
        json.dumps(
            dict(
                history=asdict(history),
                assumptions=assumptions.model_dump(),
                policy="business-signs-and-issuer-earnings-v1",
            ),
            sort_keys=True,
        ),
        category="assessment",
    )
    assessment = render_assessment(
        history, quote, profile, artifacts, assumptions, now=provider.now
    )
    history_sources = list(
        dict.fromkeys(f.url for w in history.annual + history.interim for f in w.facts.values())
    )
    return [
        ("research", "\n".join(news_lines), [news.url]),
        ("fundamental", "\n".join(lines), [r.url for name, r in records.items() if name != "news"]),
        ("assessment", assessment, history_sources + [quote.url, profile.url]),
    ]
