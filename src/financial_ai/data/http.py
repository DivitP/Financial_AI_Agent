"""Shared, provider-aware HTTP policy with injectable transport for offline tests."""

from __future__ import annotations

import email.utils
import hashlib
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from collections import OrderedDict
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
        transport: Transport | None = None,
        *,
        timeout_seconds: float = 15.0,
        cache_ttl_seconds: float = 300.0,
        max_response_bytes: int = 2_000_000,
        max_retries: int = 2,
        provider_concurrency: int = 2,
        user_agent: str = "financial-ai-agent/0.1 (+https://example.invalid)",
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        quotas=None,
        cache_max_entries: int = 128,
        cache_max_bytes: int = 16_000_000,
    ) -> None:
        if transport is None:
            from settings import get_settings
            from financial_ai.data.safe_transport import SafeTransport

            transport = SafeTransport(get_settings().document_allowed_hosts)
            if quotas is None:
                from financial_ai.quotas import current_quotas

                quotas = current_quotas()
        self.quotas = quotas
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_response_bytes = max_response_bytes
        self.max_retries = max_retries
        self.provider_concurrency = provider_concurrency
        self.user_agent = user_agent
        self.sleep = sleep
        self.monotonic = monotonic
        if cache_max_entries < 1 or cache_max_bytes < 1 or provider_concurrency < 1:
            raise ValueError("Cache capacities and provider concurrency must be positive")
        self.cache_max_entries, self.cache_max_bytes = cache_max_entries, cache_max_bytes
        self._cache: OrderedDict[str, tuple[float, HttpResponse]] = OrderedDict()
        self._inflight: dict[str, Future[HttpResponse]] = {}
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_bytes = self._evictions = self._deduplicated = 0

    def health_summary(self) -> dict:
        """Return aggregate counters only; never cache keys, URLs, headers or bodies."""
        with self._lock:
            now = self.monotonic()
            return {
                "state": "observed",
                "scope": "attached in-process HTTP client",
                "entries": len(self._cache),
                "active_entries": sum(expires > now for expires, _ in self._cache.values()),
                "expired_entries": sum(expires <= now for expires, _ in self._cache.values()),
                "inflight": len(self._inflight),
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "ttl_seconds": self.cache_ttl_seconds,
                "bytes": self._cache_bytes,
                "max_bytes": self.cache_max_bytes,
                "evictions": self._evictions,
                "deduplicated": self._deduplicated,
                "hit_ratio": self._cache_hits / max(1, self._cache_hits + self._cache_misses),
            }

    def fetch(self, request: HttpRequest) -> HttpResponse:
        from financial_ai.observability import record_event

        key = self._cache_key(request)
        hit = None
        owner = False
        future = None
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > self.monotonic():
                self._cache_hits += 1
                self._cache.move_to_end(key)
                hit = cached[1]
            else:
                if cached:
                    self._cache_bytes -= len(self._cache.pop(key)[1].body)
                future = self._inflight.get(key)
                if future is None:
                    self._cache_misses += 1
                    future = Future()
                    self._inflight[key] = future
                    owner = True
                else:
                    self._deduplicated += 1
        if hit is not None:
            record_event("cache", request.provider, "hit")
            return hit
        assert future is not None
        if not owner:
            record_event("cache", request.provider, "deduplicated")
            return future.result(timeout=self.timeout_seconds * (self.max_retries + 1) + 30)

        record_event("cache", request.provider, "miss")
        try:
            response = self._fetch_uncached(request)
            if 200 <= response.status_code < 300 and len(response.body) <= self.cache_max_bytes:
                with self._lock:
                    for expired in [
                        k for k, (expires, _) in self._cache.items() if expires <= self.monotonic()
                    ]:
                        self._cache_bytes -= len(self._cache.pop(expired)[1].body)
                    while self._cache and (
                        len(self._cache) >= self.cache_max_entries
                        or self._cache_bytes + len(response.body) > self.cache_max_bytes
                    ):
                        self._cache_bytes -= len(self._cache.popitem(last=False)[1][1].body)
                        self._evictions += 1
                    self._cache[key] = (self.monotonic() + self.cache_ttl_seconds, response)
                    self._cache_bytes += len(response.body)
            future.set_result(response)
            return response
        except Exception as error:
            future.set_exception(error)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def _fetch_uncached(self, request: HttpRequest) -> HttpResponse:
        from financial_ai.quotas import active_quotas

        quotas = active_quotas() or self.quotas
        semaphore = self._semaphore(request.provider)
        if not semaphore.acquire(blocking=False):
            from financial_ai.quotas import QuotaExceeded

            raise QuotaExceeded("Provider concurrency", 1)
        try:
            for attempt in range(self.max_retries + 1):
                enriched = HttpRequest(
                    provider=request.provider,
                    url=request.url,
                    method=request.method,
                    headers={"User-Agent": self.user_agent, **request.headers},
                    body=request.body,
                )
                from contextlib import nullcontext
                from financial_ai.quotas import QuotaExceeded

                with (
                    quotas.slot(
                        "provider:" + request.provider, quotas.settings.provider_concurrency
                    )
                    if quotas
                    else nullcontext()
                ):
                    if quotas:
                        quotas.charge("calls")
                        if request.provider == "article":
                            quotas.charge("articles")
                        quotas.provider(request.provider)
                    from financial_ai.observability import observe

                    with observe("provider", request.provider, attempt=attempt + 1) as event:
                        response = self.transport(
                            enriched, self.timeout_seconds, self.max_response_bytes
                        )
                        event["status_code"] = response.status_code
                        event["outcome"] = "error" if response.status_code >= 400 else "ok"
                if len(response.body) > self.max_response_bytes:
                    raise HttpResponseTooLargeError(
                        "provider response exceeded configured size limit"
                    )
                if response.status_code != 429 and response.status_code < 500:
                    return response
                if attempt == self.max_retries:
                    if response.status_code == 429:
                        if quotas:
                            quotas.cooldown(
                                request.provider, max(60, self._retry_delay(response, attempt))
                            )
                        raise QuotaExceeded(
                            "Provider free-tier", self._retry_delay(response, attempt)
                        )
                    return response
                delay = self._retry_delay(response, attempt)
                maximum = quotas.settings.max_retry_delay_seconds if quotas else 10
                if delay > maximum:
                    if quotas:
                        quotas.cooldown(request.provider, delay)
                    raise QuotaExceeded("Provider retry budget", delay)
                self.sleep(delay)
        finally:
            semaphore.release()
        raise RuntimeError("unreachable")

    def _semaphore(self, provider: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._semaphores.setdefault(
                provider, threading.BoundedSemaphore(self.provider_concurrency)
            )

    def fetch_many(self, requests: list[HttpRequest]) -> list[HttpResponse | Exception]:
        """Bounded dispatch, coalesced duplicates, input order and independent failures.

        This is not a claim that providers offer a bulk endpoint. Existing quotas,
        concurrency, cache and retry policies apply to every distinct request.
        """
        if len(requests) > 50:
            raise ValueError("A provider batch is limited to 50 requests")
        with ThreadPoolExecutor(max_workers=min(8, self.provider_concurrency)) as pool:
            futures: dict[str, Future] = {}
            for request in requests:
                key = self._cache_key(request)
                if key not in futures:
                    futures[key] = pool.submit(copy_context().run, self.fetch, request)
            results: list[HttpResponse | Exception] = []
            for request in requests:
                try:
                    results.append(futures[self._cache_key(request)].result())
                except Exception as error:
                    results.append(error)
            return results

    @staticmethod
    def _cache_key(request: HttpRequest) -> str:
        digest = hashlib.sha256()
        digest.update(
            json.dumps(
                [
                    request.provider,
                    request.method.upper(),
                    request.url,
                    sorted((key.lower(), value) for key, value in request.headers.items()),
                ]
            ).encode()
        )
        digest.update(request.body or b"")
        return digest.hexdigest()

    @staticmethod
    def _retry_delay(response: HttpResponse, attempt: int) -> float:
        retry_after = next(
            (v for k, v in response.headers.items() if k.lower() == "retry-after"), None
        )
        if retry_after:
            try:
                import math

                value = float(retry_after)
                if math.isfinite(value):
                    return max(0.0, value)
            except ValueError:
                try:
                    parsed = email.utils.parsedate_to_datetime(retry_after)
                except (ValueError, TypeError, OverflowError):
                    return float(2**attempt)
                if parsed.tzinfo is not None:
                    return max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        return float(2**attempt)
