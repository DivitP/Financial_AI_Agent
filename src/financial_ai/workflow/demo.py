"""Explicit offline deployment demonstration. Never a live research provider."""

import asyncio

from financial_ai.workflow.research import InitialResearchWorkflow


def handler(repository, run_id):
    async def fixture():
        return {
            "provider": "offline-demo",
            "name": "OFFLINE DEMO — not live financial research",
            "notice": "Synthetic deployment fixture only. No market data was collected.",
        }

    def step(lane):
        if lane == "collect":
            asyncio.run(
                InitialResearchWorkflow(
                    repository, dict.fromkeys(InitialResearchWorkflow.required_lanes, fixture)
                ).run(run_id)
            )

    return step
