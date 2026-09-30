"""Offline worker handler: fixture data only, never use for investment research."""

import asyncio

from financial_ai.workflow.research import InitialResearchWorkflow


def handler(repository, run_id):
    async def collect():
        return {"provider": "offline-fixture", "price": 200, "notice": "TEST DATA ONLY"}

    def step(lane):
        if lane == "collect":
            workflow = InitialResearchWorkflow(
                repository, {name: collect for name in InitialResearchWorkflow.required_lanes}
            )
            asyncio.run(workflow.run(run_id))

    return step
