"""Typed optional forecast-lane result shared by the API and workflow."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from financial_ai.kronos.preprocessing import Candle


class KronosForecastData(BaseModel):
    model_config = ConfigDict(extra="allow")
    model_version: str
    device: Literal["cpu", "mps", "cuda"]
    as_of: AwareDatetime
    candles: list[Candle]
    paths: list[list[Candle]]
    cache_hit: bool
    research_only: bool


class KronosResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "disabled", "skipped", "completed", "failed", "cancelled"]
    quality: Literal["experimental", "promoted"] = "experimental"
    warning: str | None = None
    cache_key: str | None = None
    model_run_id: str | None = None
    forecast: KronosForecastData | None = None
    validation: dict[str, object] | None = None
