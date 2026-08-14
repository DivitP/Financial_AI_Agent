"""Shared, provider-aware HTTP policy with injectable transport for offline tests."""

from __future__ import annotations

import email.utils
import hashlib
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping


@dataclass(frozen=True)
class HttpRequest:
    provider: str
    url: str
    method: str = "GET"
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpResponseTooLargeError(RuntimeError):
    pass


Transport = Callable[[HttpRequest, float, int], HttpResponse]


class SharedHttpClient:
    """Synchronous client that centralizes cache, retry, dedupe, and provider limits."""

    def __init__(
        self,
        transport: Transport,
        *,
        timeout_seconds: float = 15.0,
        cache_ttl_seconds: float = 300.0,
        max_response_bytes: int = 2_000_000,
        max_retries: int = 2,
        provider_concurrency: int = 2,
        user_agent: str = "financial-ai-agent/0.1 (+https://example.invalid)",
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_response_bytes = max_response_bytes
        self.max_retries = max_retries
        self.provider_concurrency = provider_concurrency
        self.user_agent = user_agent
        self.sleep = sleep
        self.monotonic = monotonic
        self._cache: dict[str, tuple[float, HttpResponse]] = {}
        self._inflight: dict[str, Future[HttpResponse]] = {}
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()

    def fetch(self, request: HttpRequest) -> HttpResponse:
        key = self._cache_key(request)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > self.monotonic():
                return cached[1]
            future = self._inflight.get(key)
            if future is None:
                future = Future()
                self._inflight[key] = future
                owner = True
            else:
                owner = False
        if not owner:
            return future.result()

        try:
            response = self._fetch_uncached(request)
            with self._lock:
                self._cache[key] = (self.monotonic() + self.cache_ttl_seconds, response)
            future.set_result(response)
            return response
        except Exception as error:
            future.set_exception(error)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def _fetch_uncached(self, request: HttpRequest) -> HttpResponse:
        semaphore = self._semaphore(request.provider)
        with semaphore:
            for attempt in range(self.max_retries + 1):
                enriched = HttpRequest(
                    provider=request.provider,
                    url=request.url,
                    method=request.method,
                    headers={"User-Agent": self.user_agent, **request.headers},
                    body=request.body,
                )
                response = self.transport(enriched, self.timeout_seconds, self.max_response_bytes)
                if len(response.body) > self.max_response_bytes:
                    raise HttpResponseTooLargeError("provider response exceeded configured size limit")
                if response.status_code != 429 and response.status_code < 500:
                    return response
                if attempt == self.max_retries:
                    return response
                self.sleep(self._retry_delay(response, attempt))
        raise RuntimeError("unreachable")

    def _semaphore(self, provider: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._semaphores.setdefault(provider, threading.BoundedSemaphore(self.provider_concurrency))

    @staticmethod
    def _cache_key(request: HttpRequest) -> str:
        digest = hashlib.sha256()
        digest.update(request.provider.encode())
        digest.update(request.method.encode())
        digest.update(request.url.encode())
        digest.update(request.body or b"")
        for key, value in sorted(request.headers.items()):
            if key.lower() != "authorization":
                digest.update(f"{key}:{value}".encode())
        return digest.hexdigest()

    @staticmethod
    def _retry_delay(response: HttpResponse, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                if parsed.tzinfo is not None:
                    return max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        return float(2**attempt)
