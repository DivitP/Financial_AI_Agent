"""Watchlist CRUD; intentionally no research scheduling side effects."""

from uuid import UUID
from fastapi import APIRouter
from pydantic import Field, field_validator

from financial_ai.api.errors import ApiError
from financial_ai.api.schemas import ApiSchema, CreateResearchJobRequest
from financial_ai.storage.watchlists import Watchlists


class WatchlistName(ApiSchema):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class WatchlistItem(ApiSchema):
    ticker: str = Field(min_length=1, max_length=15)
    notes: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, value):
        return CreateResearchJobRequest.validate_ticker(value)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        if any(not v.strip() or len(v.strip()) > 40 for v in values):
            raise ValueError("tags must be 1–40 characters")
        return list(dict.fromkeys(v.strip().lower() for v in values))


def watchlist_router(store: Watchlists):
    router = APIRouter(prefix="/api/v1/watchlists", tags=["watchlists"])

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except KeyError:
            raise ApiError("watchlist_not_found", "Watchlist was not found.", 404) from None

    @router.get("")
    def lists():
        return store.lists()

    @router.post("", status_code=201)
    def create(payload: WatchlistName):
        return store.create(payload.name)

    @router.get("/{list_id}")
    def detail(list_id: UUID):
        return call(store.detail, list_id)

    @router.patch("/{list_id}")
    def rename(list_id: UUID, payload: WatchlistName):
        call(store.change, list_id, name=payload.name)
        return call(store.detail, list_id)

    @router.delete("/{list_id}")
    def remove(list_id: UUID):
        call(store.change, list_id, delete=True)
        return {"deleted": True}

    @router.put("/{list_id}/items")
    def save_item(list_id: UUID, payload: WatchlistItem):
        call(store.change, list_id, item=payload)
        return call(store.detail, list_id)

    @router.delete("/{list_id}/items/{ticker}")
    def remove_item(list_id: UUID, ticker: str):
        # Reuse the same validation and normalization as item writes.
        from pydantic import ValidationError

        try:
            symbol = WatchlistItem(ticker=ticker).ticker
        except ValidationError:
            raise ApiError("invalid_request", "Invalid ticker.", 422) from None
        call(store.change, list_id, ticker=symbol)
        return call(store.detail, list_id)

    return router
