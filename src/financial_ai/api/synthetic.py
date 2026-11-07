"""Read-only public fixture catalog; never serves user documents or filesystem paths."""

from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from financial_ai.api.errors import ApiError
from financial_ai.providers.synthetic import SyntheticCollector, NOTICE


def synthetic_router(base_url: str) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/synthetic-evidence/{record_id}",
        response_class=PlainTextResponse,
        tags=["synthetic"],
    )
    def record(record_id: UUID):
        try:
            source = SyntheticCollector(base_url).lookup(record_id)
        except KeyError:
            raise ApiError(
                "synthetic_evidence_not_found", "Unknown synthetic evidence record", 404
            ) from None
        return PlainTextResponse(
            NOTICE + "\n\n" + source.model_dump_json(indent=2),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return router
