"""Atomic SQLite budgets shared by API, workers and provider adapters."""

import math
import time
from contextlib import closing, contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps
from uuid import uuid4

from financial_ai.storage.database import Database
from settings import get_settings


class QuotaExceeded(RuntimeError):
    def __init__(self, resource, retry_after=60):
        self.retry_after = max(1, math.ceil(retry_after))
        self.resource = resource
        super().__init__(
            f"{resource} limit reached. Saved results remain available. "
            f"Retry after {self.retry_after}s; per-run budgets do not reset on retry."
        )


_context: ContextVar[tuple | None] = ContextVar("research_budget", default=None)


class Quotas:
    def __init__(self, database, settings=None, clock=time.time):
        self.database, self.settings, self.clock = database, settings or get_settings(), clock

    @contextmanager
    def context(self, run_id=None):
        token = _context.set((self, str(run_id) if run_id is not None else None))
        try:
            yield
        finally:
            _context.reset(token)

    def consume(self, scope, resource, limit, amount=1, *, persistent=False):
        now = self.clock()
        window = 0 if persistent else int(now // 60) + 1
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM quota_usage WHERE window > 0 AND window < ?", (int(now // 60),))
            row = db.execute(
                "SELECT used FROM quota_usage WHERE scope=? AND resource=? AND window=?",
                (scope, resource, window),
            ).fetchone()
            if amount < 0 or (row["used"] if row else 0) + amount > limit:
                raise QuotaExceeded(resource, 60 - now % 60)
            db.execute(
                """INSERT INTO quota_usage VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, resource, window) DO UPDATE SET used=used+excluded.used""",
                (scope, resource, window, amount),
            )

    def charge(self, resource, amount=1):
        context = _context.get()
        run_id = (
            context[1]
            if context and context[0].database.path.resolve() == self.database.path.resolve()
            else None
        )
        limits = {
            "calls": self.settings.run_call_budget,
            "articles": self.settings.run_article_budget,
            "models": self.settings.run_model_budget,
        }
        self.consume(
            "run:" + run_id if run_id else "standalone",
            resource,
            limits[resource],
            amount,
            persistent=run_id is not None,
        )

    def provider(self, name):
        with closing(self.database.connect()) as db:
            row = db.execute(
                "SELECT until FROM quota_cooldowns WHERE provider=?", (name,)
            ).fetchone()
        if row and row[0] > self.clock():
            raise QuotaExceeded("Provider cooldown", row[0] - self.clock())
        self.consume(
            "provider:" + name, "provider requests", self.settings.provider_rate_limit_per_minute
        )

    def cooldown(self, name, seconds):
        with closing(self.database.connect()) as db, db:
            db.execute(
                """INSERT INTO quota_cooldowns VALUES (?, ?)
                ON CONFLICT(provider) DO UPDATE SET until=MAX(until, excluded.until)""",
                (name, self.clock() + max(1, seconds)),
            )

    @contextmanager
    def slot(self, scope, limit):
        token = str(uuid4())
        now = self.clock()
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM quota_leases WHERE expires<=?", (now,))
            count = db.execute(
                "SELECT COUNT(*) FROM quota_leases WHERE scope=?", (scope,)
            ).fetchone()[0]
            if count >= limit:
                raise QuotaExceeded("Concurrent " + scope, 1)
            db.execute("INSERT INTO quota_leases VALUES (?, ?, ?)", (token, scope, now + 600))
        try:
            yield
        finally:
            with closing(self.database.connect()) as db, db:
                db.execute("DELETE FROM quota_leases WHERE id=?", (token,))


@lru_cache(maxsize=1)
def default_quotas():
    database = Database(get_settings().database_path)
    database.migrate_to_latest()
    return Quotas(database)


def current_quotas():
    context = _context.get()
    return context[0] if context else default_quotas()


def active_quotas():
    context = _context.get()
    return context[0] if context else None


def research_budget(method):
    @wraps(method)
    async def wrapped(self, run_id, *args, **kwargs):
        quotas = Quotas(self.repository.database)
        with quotas.context(run_id):
            with quotas.slot("research workflows", quotas.settings.max_running_jobs):
                import asyncio

                return await asyncio.wait_for(method(self, run_id, *args, **kwargs), timeout=540)

    return wrapped


def limited_model(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        quotas = current_quotas()
        provider = getattr(self, "provider", "chat")
        with quotas.slot("model:" + provider, quotas.settings.provider_concurrency):
            quotas.charge("models")
            quotas.provider(provider)
            try:
                import asyncio

                return await asyncio.wait_for(method(self, *args, **kwargs), timeout=120)
            except Exception as error:
                if getattr(error, "status_code", None) == 429:
                    quotas.cooldown(provider, 60)
                    raise QuotaExceeded("Model provider free-tier") from None
                raise

    setattr(wrapped, "_quota_enforced", True)
    return wrapped


@limited_model
async def _complete_chat(self, messages, *, token_budget):
    return await self.complete(messages, token_budget=token_budget)


async def complete_chat(provider, messages, *, token_budget):
    if getattr(provider.complete, "_quota_enforced", False):
        return await provider.complete(messages, token_budget=token_budget)
    return await _complete_chat(provider, messages, token_budget=token_budget)
