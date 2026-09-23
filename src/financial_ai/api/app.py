"""FastAPI application factory for the replacement API."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator, Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from fastapi import FastAPI, Header, Request, Query
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from settings import get_settings

from financial_ai.api.errors import (
    ApiError,
    api_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from financial_ai.api.logging import configure_logging
from financial_ai.api.schemas import (
    CreateResearchJobRequest,
    HealthResponse,
    JobResponse,
    ResearchRunResponse,
    ResearchSnapshotResponse,
    ReportResponse,
    VersionResponse,
    KronosResponse,
    HistoryUpdate,
    HistoryItem,
)
from financial_ai.domain.models import AssetType, Instrument, ResearchRun
from financial_ai.llm import validate_chat_configuration
from financial_ai.llm.providers import create_chat_provider
from financial_ai.retrieval.index import ResearchIndex
from financial_ai.retrieval.qa import ResearchQA, Question, AnswerRejected
from financial_ai.storage.database import Database
from financial_ai.storage.repositories import ResearchRepository
from financial_ai.storage.history import ResearchHistory
from financial_ai.api.compare import comparison_router
from financial_ai.analysis.delta import ResearchDelta
from financial_ai.storage.watchlists import Watchlists
from financial_ai.api.watchlists import watchlist_router
from financial_ai.workflow.jobs import Job, LocalResearchJobRunner
from financial_ai.workflow.kronos import KronosWorkflowNode


API_VERSION = "v1"
APP_VERSION = "0.1.0"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response


def create_app(database_path: Path | str = Path("data/runtime/financial_ai.db")) -> FastAPI:
    """Create an API that is operational without any external-provider credentials."""

    validate_chat_configuration(get_settings())
    database = Database(database_path)
    database.migrate_to_latest()
    repository = ResearchRepository(database)
    history = ResearchHistory(database)
    delta = ResearchDelta(database)
    runner = LocalResearchJobRunner(database)
    logger = configure_logging()

    app = FastAPI(
        title="Financial AI Research API",
        version=APP_VERSION,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.database = database
    app.include_router(comparison_router(database))
    app.include_router(watchlist_router(Watchlists(database)))
    app.state.repository = repository
    app.state.runner = runner
    app.state.kronos = KronosWorkflowNode(repository, get_settings())
    app.state.qa = ResearchQA(
        ResearchIndex(database, Path(database_path).with_suffix(".index.db")),
        create_chat_provider(get_settings()),
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/api/v1/research-runs/{run_id}/qa", tags=["research"])
    def qa_history(run_id: UUID):
        _run_or_error(repository, run_id)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM qa_history WHERE run_id=? ORDER BY id DESC LIMIT 100", (str(run_id),)
            ).fetchall()
        return [
            {"id": r["id"], "question": r["question"], "answer": json.loads(r["answer_json"])}
            for r in reversed(rows)
        ]

    @app.post("/api/v1/research-runs/{run_id}/qa", tags=["research"])
    async def ask_question(run_id: UUID, payload: Question):
        run = _run_or_error(repository, run_id)
        try:
            answer = await app.state.qa.answer(run_id, run["symbol"], payload.question)
        except AnswerRejected:
            raise ApiError(
                "invalid_answer_citations",
                "The answer could not be verified. Please try again.",
                422,
            ) from None
        except Exception:
            raise ApiError(
                "qa_unavailable", "Research Q&A is temporarily unavailable.", 503
            ) from None
        with database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO qa_history(run_id, question, answer_json, created_at) VALUES (?, ?, ?, ?)",
                (str(run_id), payload.question, json.dumps(answer), answer["as_of"]),
            )
            turn_id = cursor.lastrowid

        async def stream():
            # No model tokens leave the server before the whole answer is validated.
            for claim in answer["claims"]:
                yield "event: claim\ndata: " + json.dumps(claim) + "\n\n"
                await asyncio.sleep(0)
            yield (
                "event: complete\ndata: "
                + json.dumps({"id": turn_id, "question": payload.question, "answer": answer})
                + "\n\n"
            )

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse, tags=["system"])
    def ready() -> HealthResponse:
        database.current_version()
        return HealthResponse(status="ok")

    @app.get("/version", response_model=VersionResponse, tags=["system"])
    def version() -> VersionResponse:
        return VersionResponse(version=APP_VERSION, api_version=API_VERSION)

    @app.post(
        "/api/v1/research-jobs", response_model=JobResponse, status_code=202, tags=["research"]
    )
    def create_research_job(payload: CreateResearchJobRequest, request: Request) -> JobResponse:
        instrument = _saved_instrument(database, payload.ticker)
        run = ResearchRun(
            id=uuid4(),
            instrument_id=instrument.id,
            requested_at=datetime.now(UTC),
            provider_config_version="local-v1",
            scope=payload.model_dump(exclude={"ticker"}, exclude_none=True),
        )
        with database.transaction() as connection:
            repository.add_instrument(instrument, connection)
            repository.add_run(run, connection)
            job = runner.create(run.id, {"ticker": instrument.symbol}, connection)
        logger.info("research job queued", extra={"correlation_id": request.state.correlation_id})
        return _job_response(job, request.state.correlation_id)

    @app.post(
        "/api/v1/research-runs",
        response_model=ResearchRunResponse,
        status_code=202,
        tags=["research"],
    )
    def create_research_run(
        payload: CreateResearchJobRequest, request: Request
    ) -> ResearchRunResponse:
        instrument = _saved_instrument(database, payload.ticker)
        run = ResearchRun(
            id=uuid4(),
            instrument_id=instrument.id,
            requested_at=datetime.now(UTC),
            provider_config_version="initial-research-v1",
            scope=payload.model_dump(exclude={"ticker"}, exclude_none=True),
        )
        with database.transaction() as connection:
            repository.add_instrument(instrument, connection)
            repository.add_run(run, connection)
            runner.create(run.id, {"ticker": instrument.symbol}, connection)
        return ResearchRunResponse(
            id=run.id,
            status=run.status.value,
            ticker=instrument.symbol,
            asset_type=instrument.asset_type.value,
            correlation_id=request.state.correlation_id,
        )

    @app.get("/api/v1/research-runs/{run_id}/delta", tags=["history"])
    def changes_since_last_run(run_id: UUID, previous_run_id: UUID | None = None):
        try:
            return delta.compare(run_id, previous_run_id)
        except KeyError:
            raise ApiError("run_not_found", "Research run not found.", 404) from None
        except ValueError as exc:
            raise ApiError("invalid_comparison", str(exc), 409) from None

    @app.get("/api/v1/research-runs", response_model=list[HistoryItem], tags=["history"])
    def list_history(
        q: str = Query(default="", max_length=80),
        status: Literal["pending", "running", "completed", "failed", "cancelled"] | None = None,
        archive: Literal["active", "archived", "all"] = "active",
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return history.list(q=q, status=status, archive=archive, limit=limit, offset=offset)

    @app.patch("/api/v1/research-runs/{run_id}/history", tags=["history"])
    def update_history(run_id: UUID, payload: HistoryUpdate):
        _run_or_error(repository, run_id)
        history.update(run_id, payload.model_dump(exclude_unset=True))
        return history.reopen(run_id)

    @app.get("/api/v1/research-runs/{run_id}/history", tags=["history"])
    def reopen_history(run_id: UUID, version: int | None = Query(default=None, ge=1)):
        _run_or_error(repository, run_id)
        try:
            return history.reopen(run_id, version)
        except KeyError:
            raise ApiError(
                "report_version_not_found", "Saved report version was not found.", 404
            ) from None

    @app.get(
        "/api/v1/research-runs/{run_id}", response_model=ResearchRunResponse, tags=["research"]
    )
    def get_research_run(run_id: UUID, request: Request) -> ResearchRunResponse:
        row = _run_or_error(repository, run_id)
        return _run_response(row, request.state.correlation_id)

    @app.get(
        "/api/v1/research-runs/{run_id}/snapshot",
        response_model=list[ResearchSnapshotResponse],
        tags=["research"],
    )
    def get_initial_snapshot(run_id: UUID) -> list[ResearchSnapshotResponse]:
        _run_or_error(repository, run_id)
        return [
            ResearchSnapshotResponse(
                lane=row["lane"],
                status=row["status"],
                payload=(
                    app.state.kronos.read(run_id).model_dump(mode="json")
                    if row["lane"] == "kronos"
                    else json.loads(row["payload_json"])
                    if row["payload_json"]
                    else None
                ),
                error_message=row["error_message"],
            )
            for row in repository.snapshots(run_id)
        ]

    @app.get(
        "/api/v1/research-runs/{run_id}/forecast", response_model=KronosResponse, tags=["research"]
    )
    def get_forecast(run_id: UUID, include_experimental: bool = False):
        _run_or_error(repository, run_id)
        return app.state.kronos.read(run_id, include_experimental=include_experimental)

    @app.post(
        "/api/v1/research-runs/{run_id}/forecast", response_model=KronosResponse, tags=["research"]
    )
    async def run_forecast(run_id: UUID, include_experimental: bool = False):
        _run_or_error(repository, run_id)
        try:
            await app.state.kronos.run(run_id)
        except Exception:
            repository.upsert_snapshot(
                run_id, "kronos", "failed", None, "Optional forecast unavailable"
            )
        return app.state.kronos.read(run_id, include_experimental=include_experimental)

    @app.get(
        "/api/v1/research-runs/{run_id}/reports/latest",
        response_model=ReportResponse,
        tags=["research"],
    )
    def get_latest_report(run_id: UUID) -> ReportResponse:
        _run_or_error(repository, run_id)
        row = repository.latest_report(run_id)
        if row is None:
            raise ApiError("report_not_found", "No verified report is available for this run.", 404)
        return ReportResponse(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            version=int(row["version"]),
            as_of=datetime.fromisoformat(row["as_of"]),
            model_configuration=json.loads(row["model_config_json"]),
            decision_brief=json.loads(row["decision_brief_json"]),
            sections=json.loads(row["sections_json"]),
            evidence_links=repository.report_evidence_links(UUID(row["id"])),
        )

    @app.get("/api/v1/research-runs/{run_id}/events", tags=["research"])
    async def stream_research_run(
        run_id: UUID,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        """Stream durable job events for a run; browser reconnects use Last-Event-ID."""
        _run_or_error(repository, run_id)
        try:
            cursor = int(last_event_id or 0)
        except ValueError as error:
            raise ApiError(
                "invalid_event_cursor", "Last-Event-ID must be an integer.", 422
            ) from error

        async def events() -> AsyncIterator[str]:
            nonlocal cursor
            while True:
                with database.connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT job_events.id, job_events.kind, job_events.payload_json
                        FROM job_events JOIN jobs ON jobs.id = job_events.job_id
                        WHERE jobs.run_id=? AND job_events.id>? ORDER BY job_events.id
                        """,
                        (str(run_id), cursor),
                    ).fetchall()
                for event in rows:
                    cursor = int(event["id"])
                    yield f"id: {cursor}\nevent: {event['kind']}\ndata: {event['payload_json']}\n\n"
                row = repository.get_run(run_id)
                if row is None or row["status"] in {"completed", "failed", "cancelled"}:
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.post(
        "/api/v1/research-runs/{run_id}/cancel",
        response_model=ResearchRunResponse,
        tags=["research"],
    )
    def cancel_research_run(run_id: UUID, request: Request) -> ResearchRunResponse:
        row = _run_or_error(repository, run_id)
        if row["status"] not in {"pending", "running"}:
            raise ApiError("run_not_cancellable", "Research run cannot be cancelled.", 409)
        with database.transaction() as connection:
            repository.update_run_status(run_id, "cancelled", connection)
            job = connection.execute(
                "SELECT id FROM jobs WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
                (str(run_id),),
            ).fetchone()
            if job:
                connection.execute(
                    "UPDATE jobs SET status='cancelled', updated_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), job["id"]),
                )
        return _run_response(_run_or_error(repository, run_id), request.state.correlation_id)

    @app.post(
        "/api/v1/research-runs/{run_id}/retry",
        response_model=ResearchRunResponse,
        tags=["research"],
    )
    def retry_research_run(run_id: UUID, request: Request) -> ResearchRunResponse:
        row = _run_or_error(repository, run_id)
        if row["status"] not in {"failed", "cancelled"}:
            raise ApiError(
                "run_not_retryable", "Only failed or cancelled runs can be retried.", 409
            )
        with database.transaction() as connection:
            repository.update_run_status(run_id, "pending", connection)
            runner.create(run_id, {"retry": True}, connection)
        return _run_response(_run_or_error(repository, run_id), request.state.correlation_id)

    @app.post("/api/v1/research-jobs/{job_id}/run", response_model=JobResponse, tags=["research"])
    def run_research_job(job_id: UUID, request: Request) -> JobResponse:
        try:
            job = runner.run(job_id)
        except KeyError as error:
            raise ApiError("job_not_found", "Research job was not found.", 404) from error
        return _job_response(job, request.state.correlation_id)

    @app.delete("/api/v1/research-jobs/{job_id}", response_model=JobResponse, tags=["research"])
    def cancel_research_job(job_id: UUID, request: Request) -> JobResponse:
        if not runner.cancel(job_id):
            raise ApiError("job_not_cancellable", "Research job cannot be cancelled.", 409)
        return _job_response(runner._job(job_id), request.state.correlation_id)

    @app.get("/api/v1/research-jobs/{job_id}/events", tags=["research"])
    async def stream_research_job(
        job_id: UUID,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            cursor = int(last_event_id or 0)
        except ValueError as error:
            raise ApiError(
                "invalid_event_cursor", "Last-Event-ID must be an integer.", 422
            ) from error

        async def events() -> AsyncIterator[str]:
            nonlocal cursor
            while True:
                for event in runner.events_after(job_id, cursor):
                    cursor = event.id
                    payload = {"id": event.id, "kind": event.kind, **event.payload}
                    yield f"id: {event.id}\nevent: {event.kind}\ndata: {json.dumps(payload)}\n\n"
                try:
                    status = runner._job(job_id).status
                except KeyError:
                    yield 'event: error\ndata: {"code":"job_not_found"}\n\n'
                    return
                if status in {"completed", "failed", "cancelled"}:
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app


def _job_response(job: Job, correlation_id: str) -> JobResponse:
    return JobResponse(
        id=job.id, run_id=job.run_id, status=job.status, correlation_id=correlation_id
    )


def _saved_instrument(database: Database, ticker: str) -> Instrument:
    with database.connect() as db:
        row = db.execute(
            "SELECT * FROM instruments WHERE symbol=? AND asset_type='equity' AND exchange=''",
            (ticker,),
        ).fetchone()
    return Instrument(
        id=UUID(row["id"]) if row else uuid5(NAMESPACE_URL, "financial-ai:equity:" + ticker),
        symbol=ticker,
        asset_type=AssetType.EQUITY,
        currency=row["currency"] if row else "USD",
    )


def _run_or_error(repository: ResearchRepository, run_id: UUID):
    row = repository.get_run(run_id)
    if row is None:
        raise ApiError("run_not_found", "Research run was not found.", 404)
    return row


def _run_response(row, correlation_id: str) -> ResearchRunResponse:
    return ResearchRunResponse(
        id=UUID(row["id"]),
        status=row["status"],
        ticker=row["symbol"],
        asset_type=row["asset_type"],
        correlation_id=correlation_id,
    )
