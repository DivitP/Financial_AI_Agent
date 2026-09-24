from fastapi import APIRouter
from pydantic import Field, field_validator, model_validator

from financial_ai.api.schemas import ApiSchema, CreateResearchJobRequest
from financial_ai.analysis.portfolio import PortfolioContext


class HypotheticalHolding(ApiSchema):
    ticker: str = Field(min_length=1, max_length=15)
    weight: float = Field(gt=0, le=100, allow_inf_nan=False)

    @field_validator("ticker")
    @classmethod
    def ticker_symbol(cls, value):
        return CreateResearchJobRequest.validate_ticker(value)


class PortfolioRequest(ApiSchema):
    holdings: list[HypotheticalHolding] = Field(min_length=1, max_length=10)
    candidate: HypotheticalHolding

    @model_validator(mode="after")
    def valid_weights(self):
        if len({h.ticker for h in self.holdings}) != len(self.holdings):
            raise ValueError("Holdings must have distinct tickers")
        if abs(sum(h.weight for h in self.holdings) - 100) > 0.000001:
            raise ValueError("Hypothetical holdings must total 100 percent")
        if self.candidate.weight >= 100:
            raise ValueError("Candidate weight must be below 100 percent")
        return self


def portfolio_router(database):
    router = APIRouter(tags=["portfolio-context"])

    @router.post("/api/v1/portfolio-context")
    def analyze(payload: PortfolioRequest):
        return PortfolioContext(database).analyze(payload.holdings, payload.candidate)

    return router
