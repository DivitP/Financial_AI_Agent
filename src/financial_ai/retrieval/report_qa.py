"""Report-scoped excerpt answers; model IDs, URLs and quotes are never trusted."""

import asyncio
import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from financial_ai.data.documents import document_text, UnsafeDocument, UNTRUSTED_POLICY
from financial_ai.llm.contracts import ChatMessage
from financial_ai.llm.providers import create_chat_provider
from financial_ai.storage.report_evidence import ReportEvidenceStore


class SelectedQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passage_id: str
    quote: str = Field(min_length=1, max_length=600)


class DraftQuotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[SelectedQuote] = Field(max_length=3)


async def answer_report_question(
    store: ReportEvidenceStore, report_id, ticker, question, *, provider=None
):
    store.report(report_id, ticker)
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 1000:
        raise ValueError("Enter a question between 3 and 1000 characters.")
    news = bool(
        re.search(
            r"news|article|headline|sentiment|opinion|public|press release|coverage|filing|original source",
            question,
            re.I,
        )
    )
    contexts = store.search(report_id, ticker, question, news=news)
    safe = {}
    for passage in contexts:
        try:
            document_text(json.dumps(passage))
            if document_text(passage["text"]) == passage["text"]:
                safe[passage["id"]] = passage
        except UnsafeDocument:
            continue
    result = dict(
        report_id=report_id,
        ticker=ticker,
        status="insufficient_evidence",
        claims=[],
        sources=[],
        answer="No supporting source passages were collected in this report for that question.",
    )
    if not safe:
        if news:
            result["answer"] = (
                "This report has no readable article or filing passages supporting that question. Headline-only, blocked and paywalled sources are not evidence for an article-level answer. Generate a new report to collect current source bodies."
            )
        return result
    if provider is None:
        result["status"] = "model_disabled"
        result["answer"] = (
            "Source bodies are available, but answer selection is disabled. Configure the chat provider to ask source-backed questions."
        )
        return result
    messages = [
        ChatMessage(
            role="system",
            content=(
                'Return JSON only: {"claims":[{"passage_id":"...","quote":"exact source substring"}]}. '
                "Select at most three exact excerpts answering the question, at most 24 quoted words per article URL "
                "and 120 words per filing or financial-data URL. "
                "Return empty claims if the question is unsupported. Do not invent prose, IDs, links, sentiment, "
                "recommendations or conclusions. Preserve distinctions between reporting, publisher opinion, issuer "
                "disclosures and calculations. A few articles do not measure public sentiment. "
                + UNTRUSTED_POLICY
            ),
        ),
        ChatMessage(
            role="user", content=json.dumps(dict(question=question, passages=list(safe.values())))
        ),
    ]
    try:
        response = await asyncio.wait_for(
            provider.complete(messages, token_budget=1500), timeout=35
        )
    except TimeoutError:
        result.update(
            status="timeout",
            answer="Source passage selection timed out. Please retry this question.",
        )
        return result
    try:
        draft = DraftQuotes.model_validate_json(response.content)
        counts: dict[str, int] = {}
        claims: list[dict] = []
        for selection in draft.claims:
            passage = safe.get(selection.passage_id)
            if passage is None or selection.quote not in passage["text"]:
                raise ValueError("Unverified citation or quote")
            url = passage["url"]
            counts[url] = counts.get(url, 0) + len(selection.quote.split())
            if counts[url] > (24 if passage.get("kind") == "article" else 120):
                raise ValueError("Source quote budget exceeded")
            if any(
                c["passage_id"] == passage["id"] and c["quote"] == selection.quote for c in claims
            ):
                continue
            claims.append(
                dict(
                    passage_id=passage["id"],
                    quote=selection.quote,
                    url=url,
                    title=passage["title"],
                    classification=passage["classification"],
                    published_at=passage.get("published_at"),
                    evidence_id=passage.get("evidence_id"),
                )
            )
    except (ValidationError, ValueError):
        result.update(
            status="unverified_answer",
            answer="The generated answer failed passage verification. No unverified claims or citations were displayed.",
        )
        return result
    if not claims:
        return result
    result.update(
        status="answered",
        claims=claims,
        sources=list(dict.fromkeys(c["url"] for c in claims)),
        answer="These source passages address your question. Labels describe the source, not independent verification of its claims.",
    )
    if news and re.search(r"sentiment|public|people think", question, re.I):
        result["answer"] = (
            "These passages show published coverage or author views; they do not establish representative public sentiment."
        )
    store.save_answer(report_id, ticker, question, result)
    return result


def ask_selected_report(persist_dir, ticker, report_id, question, settings):
    from pathlib import Path

    store = ReportEvidenceStore(Path(persist_dir) / "report_evidence.sqlite3")
    # Validate scope before constructing a model client or retrieving anything.
    store.report(report_id, ticker)
    return asyncio.run(
        answer_report_question(
            store, report_id, ticker, question, provider=create_chat_provider(settings)
        )
    )
