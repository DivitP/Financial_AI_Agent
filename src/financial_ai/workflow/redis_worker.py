"""Redis Streams transport; relational jobs/outbox remain the source of truth."""

import argparse
import importlib
import logging
import time
from contextlib import contextmanager
from uuid import UUID, uuid4

from financial_ai.quotas import QuotaExceeded
from financial_ai.storage.database import Database
from financial_ai.storage.repositories import ResearchRepository
from financial_ai.workflow.jobs import LocalResearchJobRunner
from settings import get_settings


class RedisResearchJobRunner(LocalResearchJobRunner):
    """Same create/cancel/events/retry interface; run requests are dispatched, not executed inline."""

    def __init__(self, database, settings, *, client=None):
        super().__init__(database)
        if not database.postgres:
            raise ValueError("Redis workers require the Postgres deployment profile")
        from redis import Redis

        self.redis = client or Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        self.stream = settings.redis_stream
        self.group = "research-workers"
        self.consumer = str(uuid4())
        self.reclaim_ms = settings.worker_reclaim_seconds * 1000

    def run(self, job_id, handler=None):
        # Application callers retain the signature; handlers execute only in a worker.
        if handler is not None:
            return super().run(job_id, handler)
        job = self._job(job_id)
        # The outbox is already committed; Redis failures must not erase the job.
        try:
            self.dispatch()
        except Exception:
            logging.getLogger(__name__).warning("Redis dispatch unavailable; durable jobs retained")
        return job

    def dispatch(self):
        from redis.exceptions import ResponseError

        try:
            self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        with self.database.transaction() as db:
            rows = db.execute(
                """SELECT o.job_id FROM job_outbox o JOIN jobs j ON j.id=o.job_id
                WHERE j.status IN ('pending','running') AND o.next_publish_at<=?
                ORDER BY j.created_at LIMIT 100""",
                (time.time(),),
            ).fetchall()
            for row in rows:
                self.redis.xadd(self.stream, {"job_id": row["job_id"]})
                db.execute(
                    "UPDATE job_outbox SET next_publish_at=? WHERE job_id=?",
                    (time.time() + 60, row["job_id"]),
                )
        return len(rows)

    @contextmanager
    def _ownership(self, job_id):
        # Session lock, not a timer: a slow healthy worker cannot be stolen by a reclaimer.
        connection = self.database.connect()
        key = int(UUID(str(job_id))) % (2**63 - 1)
        acquired = connection.raw.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
        try:
            yield bool(acquired)
        finally:
            connection.close()  # Releases the session lock, also on process death.

    def process_one(self, handler_factory):
        self.dispatch()
        claimed = self.redis.xautoclaim(
            self.stream, self.group, self.consumer, self.reclaim_ms, "0-0", count=1
        )
        entries = claimed[1]
        if not entries:
            batches = self.redis.xreadgroup(
                self.group, self.consumer, {self.stream: ">"}, count=1, block=1000
            )
            entries = batches[0][1] if batches else []
        if not entries:
            return None
        message_id, fields = entries[0]
        try:
            job_id = UUID(fields["job_id"])
        except (KeyError, ValueError):
            self.redis.xack(self.stream, self.group, message_id)
            self.redis.xdel(self.stream, message_id)
            return None
        with self._ownership(job_id) as acquired:
            if not acquired:
                return None
            try:
                job = self._job(job_id)
            except KeyError:
                job = None
            if job and job.status == "running":
                with self.database.transaction() as db:
                    db.execute("UPDATE jobs SET status='pending' WHERE id=?", (str(job_id),))
            if job and job.status not in {"completed", "cancelled", "failed"}:
                try:
                    handler = handler_factory(ResearchRepository(self.database), job.run_id)
                    job = super().run(job_id, handler)
                except QuotaExceeded:
                    return None  # Leave pending; bounded quotas reject until capacity returns.
            self.redis.xack(self.stream, self.group, message_id)
            self.redis.xdel(self.stream, message_id)
            return job


def load_handler(value):
    if not value or ":" not in value:
        raise ValueError("Set WORKER_HANDLER_FACTORY to a trusted module:function (not user input)")
    module, name = value.split(":", 1)
    return getattr(importlib.import_module(module), name)


def main():
    parser = argparse.ArgumentParser(description="Redis-backed research worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.deployment_profile != "scaled":
        parser.error("DEPLOYMENT_PROFILE=scaled is required")
    factory = load_handler(settings.worker_handler_factory)
    database = Database(settings.storage_target())
    database.migrate_to_latest()
    runner = RedisResearchJobRunner(database, settings)
    while True:
        try:
            runner.process_one(factory)
        except Exception:
            logging.getLogger(__name__).warning("Worker dependency unavailable; retrying safely")
            if args.once:
                raise RuntimeError("Worker iteration failed") from None
            time.sleep(5)
        if args.once:
            return


if __name__ == "__main__":
    main()
