"""Single-owner local worker. No daemon threads or legacy imports."""

import argparse
import time
from contextlib import closing
from uuid import UUID

from financial_ai.storage import Database, ResearchRepository
from financial_ai.workflow.jobs import LocalResearchJobRunner
from financial_ai.workflow.redis_worker import load_handler
from financial_ai.workflow.pipeline import handler
from settings import get_settings


def process_one(runner, factory):
    with closing(runner.database.connect()) as db:
        row = db.execute(
            "SELECT id, run_id FROM jobs WHERE status='pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return runner.run(
        UUID(row["id"]), factory(ResearchRepository(runner.database), UUID(row["run_id"]))
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--recover", action="store_true", help="Only when the prior local worker has stopped"
    )
    args = parser.parse_args()
    settings = get_settings()
    if settings.deployment_profile != "local":
        parser.error("Use redis_worker for the scaled profile")
    if not settings.worker_handler_factory and not settings.enable_live_research:
        parser.error("Enable live research or explicitly configure a trusted fixture/demo factory")
    factory = (
        load_handler(settings.worker_handler_factory)
        if settings.worker_handler_factory
        else handler
    )
    db = Database(settings.database_path)
    db.migrate_to_latest()
    runner = LocalResearchJobRunner(db)
    if args.recover:
        runner.recover()
    while True:
        process_one(runner, factory)
        if args.once:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
