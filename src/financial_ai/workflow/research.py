"""Initial parallel research workflow with durable, lane-level snapshots."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from financial_ai.storage.repositories import ResearchRepository


LaneCallable = Callable[[], Awaitable[dict[str, object]]]


@dataclass(frozen=True)
class Snapshot:
    lane: str
    status: str
    payload: dict[str, object] | None = None
    error: str | None = None


class InitialResearchWorkflow:
    """Runs independent lanes concurrently and persists all successful lane output."""

    required_lanes = ("instrument", "quote", "ohlcv", "filings", "statements")

    def __init__(
        self, repository: ResearchRepository, lanes: dict[str, LaneCallable], *, kronos_node=None
    ) -> None:
        missing = set(self.required_lanes) - set(lanes)
        if missing:
            raise ValueError(f"Missing initial research lanes: {', '.join(sorted(missing))}")
        self.repository = repository
        self.lanes = lanes
        self.kronos_node = kronos_node

    async def run(self, run_id: UUID) -> list[Snapshot]:
        run = self.repository.get_run(run_id)
        if run is None:
            raise KeyError("Unknown research run")
        options = json.loads(run["scope_json"])
        optional_forecast = self.kronos_node is not None or options.get("include_kronos", False)
        self.repository.update_run_status(run_id, "running")
        lane_names = list(self.required_lanes)
        results = await asyncio.gather(
            *(self.lanes[lane]() for lane in lane_names), return_exceptions=True
        )
        snapshots: list[Snapshot] = []
        with self.repository.database.transaction() as connection:
            for lane, result in zip(lane_names, results, strict=True):
                if isinstance(result, BaseException):
                    snapshot = Snapshot(lane=lane, status="failed", error=str(result)[:200])
                else:
                    snapshot = Snapshot(lane=lane, status="completed", payload=result)
                self.repository.upsert_snapshot(
                    run_id,
                    snapshot.lane,
                    snapshot.status,
                    snapshot.payload,
                    snapshot.error,
                    connection,
                )
                snapshots.append(snapshot)
            final_status = (
                "completed" if any(item.status == "completed" for item in snapshots) else "failed"
            )
            if not optional_forecast:
                self.repository.update_run_status(run_id, final_status, connection)
        # Optional output is persisted separately and cannot invalidate collection.
        if optional_forecast:
            try:
                if self.kronos_node is None:
                    from settings import get_settings
                    from financial_ai.workflow.kronos import KronosWorkflowNode

                    self.kronos_node = KronosWorkflowNode(self.repository, get_settings())
                await self.kronos_node.run(run_id)
            except Exception:
                self.repository.upsert_snapshot(
                    run_id, "kronos", "failed", None, "Optional forecast unavailable"
                )
            current = self.repository.get_run(run_id)
            if current is not None and current["status"] != "cancelled":
                self.repository.update_run_status(run_id, final_status)
        return snapshots
