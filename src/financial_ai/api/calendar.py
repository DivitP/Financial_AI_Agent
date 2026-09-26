from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter

from financial_ai.analysis.calendar import WatchlistCalendar
from financial_ai.api.errors import ApiError


def calendar_router(database):
    router = APIRouter(tags=["calendar"])

    @router.get("/api/v1/calendar")
    def calendar(
        start: date | None = None, end: date | None = None, watchlist_id: UUID | None = None
    ):
        start = start or datetime.now(UTC).date()
        try:
            end = end or start + timedelta(days=90)
        except OverflowError:
            raise ApiError(
                "invalid_calendar_range", "Date range exceeds the supported calendar.", 422
            ) from None
        if not 0 <= (end - start).days <= 366:
            raise ApiError(
                "invalid_calendar_range", "Choose an ordered date range of at most 366 days.", 422
            )
        try:
            return WatchlistCalendar(database).events(start, end, watchlist_id)
        except KeyError:
            raise ApiError("watchlist_not_found", "Watchlist not found.", 404) from None
        except ValueError as exc:
            raise ApiError("calendar_limit", str(exc), 422) from None

    return router
