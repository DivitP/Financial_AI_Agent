"""Bounded saved-data comparisons."""

from fastapi import APIRouter
from pydantic import Field, field_validator

from financial_ai.api.schemas import ApiSchema, CreateResearchJobRequest
from financial_ai.analysis.compare import ResearchComparison


class ComparisonRequest(ApiSchema):
    tickers: list[str] = Field(min_length=2, max_length=5)

    @field_validator("tickers")
    @classmethod
    def symbols(cls, values):
        symbols = [CreateResearchJobRequest.validate_ticker(v) for v in values]
        if len(set(symbols)) != len(symbols):
            raise ValueError("Choose 2–5 distinct ticker symbols")
        return symbols


def comparison_router(database):
    router = APIRouter(tags=["comparison"])
    service = ResearchComparison(database)

    @router.post("/api/v1/comparisons")
    def compare(payload: ComparisonRequest):
        return service.compare(payload.tickers)

    return router
