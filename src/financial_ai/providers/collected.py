"""Validated source material crossing from collectors into the research workflow."""

from pydantic import BaseModel, Field, AwareDatetime, HttpUrl


class CollectedLane(BaseModel):
    provider: str
    url: HttpUrl
    retrieved_at: AwareDatetime
    published_at: AwareDatetime
    text: str = Field(min_length=1, max_length=2_000_000)
    payload: dict
    limitations: list[str] = Field(default_factory=list)
