"""Stable JSON API errors with no provider or traceback details."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 400


def error_response(request: Request, *, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "correlation_id": request.state.correlation_id,
        },
    )


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return error_response(
        request, code=error.code, message=error.message, status_code=error.status_code
    )


async def validation_error_handler(request: Request, _: RequestValidationError) -> JSONResponse:
    return error_response(
        request,
        code="invalid_request",
        message="Request validation failed.",
        status_code=422,
    )


async def unexpected_error_handler(request: Request, _: Exception) -> JSONResponse:
    return error_response(
        request,
        code="internal_error",
        message="An unexpected error occurred.",
        status_code=500,
    )
