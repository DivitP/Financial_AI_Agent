"""FastAPI application factory for the replacement API."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
    VersionResponse,
)
from financial_ai.domain.models import AssetType, Instrument, ResearchRun
from financial_ai.storage.database import Database
from financial_ai.storage.repositories import ResearchRepository
from financial_ai.workflow.jobs import Job, LocalResearchJobRunner


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

    database = Database(database_path)
    database.migrate_to_latest()
    repository = ResearchRepository(database)
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
    app.state.repository = repository
    app.state.runner = runner
    app.add_middleware(CorrelationIdMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)

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
        instrument = Instrument(
            id=uuid4(),
            symbol=payload.ticker,
            asset_type=AssetType.EQUITY,
            currency="USD",
        )
        run = ResearchRun(
            id=uuid4(),
            instrument_id=instrument.id,
            requested_at=datetime.now(UTC),
            provider_config_version="local-v1",
        )
        with database.transaction() as connection:
            repository.add_instrument(instrument, connection)
            repository.add_run(run, connection)
            job = runner.create(run.id, {"ticker": instrument.symbol}, connection)
        logger.info("research job queued", extra={"correlation_id": request.state.correlation_id})
        return _job_response(job, request.state.correlation_id)

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
