"""Durable LangGraph orchestration for the evidence-first research workflow."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from financial_ai.storage.repositories import ResearchRepository


GraphNode = Callable[[], Awaitable[dict[str, object]]]


class ResearchGraphState(TypedDict, total=False):
    """The serializable state passed between bounded research graph nodes."""

    run_id: str
    outputs: dict[str, dict[str, object]]
    errors: dict[str, str]
    completed_nodes: list[str]


class PersistentResearchGraph:
    """Runs ordered nodes with SQLite checkpoints, retries, and per-node timeouts."""

    def __init__(
        self,
        repository: ResearchRepository,
        nodes: dict[str, GraphNode],
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 1,
    ) -> None:
        if not nodes:
            raise ValueError("A research graph needs at least one node.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self.repository = repository
        self.nodes = nodes
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.graph = self._build()

    def _build(self):
        builder = StateGraph(ResearchGraphState)
        previous = START
        for name in self.nodes:
            builder.add_node(name, self._node(name))
            builder.add_edge(previous, name)
            previous = name
        builder.add_edge(previous, END)
        return builder.compile()

    def _node(self, name: str):
        async def run_node(state: ResearchGraphState) -> ResearchGraphState:
            run_id = UUID(state["run_id"])
            existing = {row["node"]: row for row in self.repository.graph_checkpoints(run_id)}.get(
                name
            )
            outputs = dict(state.get("outputs", {}))
            errors = dict(state.get("errors", {}))
            completed = list(state.get("completed_nodes", []))
            if existing is not None and existing["status"] == "completed":
                outputs[name] = json.loads(existing["payload_json"] or "{}")
                if name not in completed:
                    completed.append(name)
                return {"outputs": outputs, "errors": errors, "completed_nodes": completed}

            for attempt in range(1, self.max_retries + 2):
                self.repository.upsert_graph_checkpoint(run_id, name, "running", attempt)
                try:
                    payload = await asyncio.wait_for(
                        self.nodes[name](), timeout=self.timeout_seconds
                    )
                except Exception as error:
                    message = str(error)[:200] or type(error).__name__
                    self.repository.upsert_graph_checkpoint(
                        run_id, name, "failed", attempt, error_message=message
                    )
                    if attempt <= self.max_retries:
                        continue
                    errors[name] = message
                    return {"outputs": outputs, "errors": errors, "completed_nodes": completed}
                self.repository.upsert_graph_checkpoint(run_id, name, "completed", attempt, payload)
                outputs[name] = payload
                errors.pop(name, None)
                if name not in completed:
                    completed.append(name)
                return {"outputs": outputs, "errors": errors, "completed_nodes": completed}
            raise AssertionError("unreachable")

        return run_node

    async def run(self, run_id: UUID) -> ResearchGraphState:
        """Resume from completed checkpoints and retain partial output on node failure."""

        self.repository.update_run_status(run_id, "running")
        state = await self.graph.ainvoke(
            {"run_id": str(run_id), "outputs": {}, "errors": {}, "completed_nodes": []}
        )
        status = "completed" if state.get("outputs") else "failed"
        self.repository.update_run_status(run_id, status)
        return state
