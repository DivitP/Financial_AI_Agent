"""Collect real article bodies and seed an isolated report evidence snapshot."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
import json

from financial_ai.analysis.research_assessment import assess, ValuationAssumptions
from financial_ai.providers.article_reader import ArticleReader


def collect_report_sources(
    ticker,
    history,
    records,
    artifacts,
    artifact_store,
    scope,
    *,
    reader=None,
    settings=None,
    assumptions=None,
):
    from financial_ai.reporting_legacy import text

    store, report_id = scope
    reader = reader or ArticleReader(settings)
    news = records["news"]
    company = history.issuer or (
        records["profile"].data[0].get("companyName", "") if records["profile"].data else ""
    )
    candidates = [dict(item=item, filing=False) for item in news.data[:3]]
    # Original issuer filings provide an alternative to third-party commentary.
    # These URLs come from verified SEC submissions, not links inside a document.
    if history.filings:
        filing = next(
            (f for f in history.filings if f["form"] in {"10-Q", "10-K"}), history.filings[0]
        )
        candidates.append(
            dict(
                item=dict(
                    url=filing["url"],
                    title=f"Original {filing['form']} filing",
                    publishedDate=filing["filed"],
                ),
                filing=True,
            )
        )

    def read(candidate):
        return reader.read(
            candidate["item"],
            ticker=ticker,
            company_name=company,
            issuer_filing=candidate["filing"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(read, candidates))
    lines = [
        "### Sources read for this report",
        "",
        "Reporting, author opinion and issuer disclosures are labelled separately. "
        "A source label does not independently verify the publisher's claims or measure public sentiment.",
        "",
    ]
    actual_sources = []
    for candidate, article in zip(candidates, results, strict=True):
        kind = "filing" if candidate["filing"] else "article"
        metadata = dict(
            url=article.url,
            title=article.title,
            status=article.status,
            classification=article.classification,
            classification_basis=article.classification_basis,
            kind=kind,
            published_at=article.published_at,
            retrieved_at=article.retrieved_at,
            reason=article.reason,
        )
        if article.status == "read":
            evidence = artifact_store.put_text(article.raw_html, category="article_html")
            metadata["evidence_id"] = evidence
            store.add_source(report_id, ticker, metadata, article.paragraphs)
            actual_sources.append(article.url)
            excerpt = " ".join(article.paragraphs[0].split()[:24])
            lines += [
                f"#### [{text(article.title)}]({article.url})",
                "",
                f"**Read from source · {text(article.classification)}** · "
                f"Published: {text(article.published_at)} · Retrieved: {article.retrieved_at}",
                "",
                f"> {text(excerpt)}…",
                "",
                f"Classification basis: {text(article.classification_basis)}. "
                "Follow-up questions can retrieve passages from this body.",
                "",
            ]
        else:
            # Blocked pages, RSS teasers and paywalls never become answer context.
            store.add_source(report_id, ticker, metadata)
            lines += [
                f"#### {text(article.title)}",
                "",
                f"**Not read: {text(article.status)}.** {text(article.reason)}",
                "",
            ]
    if not candidates:
        lines += ["No article or original filing destinations were discovered for this report.", ""]
    if news.notices:
        lines += ["Discovery coverage:", "", *[f"- {text(note)}" for note in news.notices], ""]

    # Store individual observations rather than indexing old reports and dumping
    # every source link into every answer. Source metadata always comes from us.
    for window in history.annual + history.interim:
        for name, fact in window.facts.items():
            passage = (
                f"Reported {name}: {fact.value:,.4f} {fact.unit}; {window.kind} "
                f"period {fact.start or 'instant/start unavailable'} to {fact.end}; "
                f"filed {fact.filed or 'unavailable'}. Concept: {fact.locator}."
            )
            store.add_source(
                report_id,
                ticker,
                dict(
                    title=f"{name} · {window.kind} {window.end}",
                    url=fact.url,
                    status="read",
                    kind="financial",
                    classification="reported financial data",
                    evidence_id=fact.evidence_id,
                    locator=fact.locator,
                    published_at=fact.filed,
                    retrieved_at=history.retrieved_at,
                ),
                [passage],
            )
    for name in ("quote", "profile"):
        record = records[name]
        if record.data:
            store.add_source(
                report_id,
                ticker,
                dict(
                    title=f"{name} snapshot",
                    url=record.url,
                    status="read",
                    kind="financial",
                    classification="provider snapshot",
                    evidence_id=artifacts[name],
                    published_at=None,
                    retrieved_at=record.retrieved_at,
                ),
                [
                    json.dumps(record.data[0], sort_keys=True)
                    + f" Retrieved {record.retrieved_at}; unknown metadata must not be inferred."
                ],
            )
    assessment = assess(
        history,
        records["quote"],
        records["profile"],
        assumptions,
        now=datetime.fromisoformat(history.retrieved_at),
    )
    for insight in (
        assessment.positive + assessment.negative + assessment.observations + assessment.monitor
    ):
        if insight.facts:
            store.add_source(
                report_id,
                ticker,
                dict(
                    title="Calculated research assessment",
                    url=insight.facts[0].url,
                    status="read",
                    kind="calculation",
                    classification="calculated analysis",
                    evidence_id=insight.facts[0].evidence_id,
                    supporting_records=[asdict(f) for f in insight.facts],
                    published_at=None,
                    retrieved_at=history.retrieved_at,
                ),
                [insight.text],
            )
    options = assumptions or ValuationAssumptions()
    for scenario in assessment.scenarios:
        earnings = assessment.metrics["basis_net_income"]
        store.add_source(
            report_id,
            ticker,
            dict(
                title=scenario["name"],
                url=earnings.facts[0].url,
                status="read",
                kind="calculation",
                classification="illustrative assumptions and calculation",
                evidence_id=earnings.facts[0].evidence_id,
                supporting_records=[asdict(f) for f in earnings.facts],
                published_at=None,
                retrieved_at=history.retrieved_at,
            ),
            [
                f"Illustrative {scenario['name']}: assumed annual earnings growth {scenario['growth']:.1%}; "
                f"exit P/E {scenario['multiple']:.1f}x; horizon {options.years} years; terminal issuer equity value "
                f"{history.currency} {scenario['terminal']:,.2f}; change versus snapshot market cap {scenario['change']:+.1%}. "
                "These are assumptions, not a price forecast or trade instruction."
            ],
        )
    return "\n".join(lines), actual_sources
