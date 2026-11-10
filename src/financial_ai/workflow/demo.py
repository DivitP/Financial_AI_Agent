"""Explicit offline deployment demonstration. Never a live research provider."""

from financial_ai.workflow.synthetic import handler as synthetic_handler


def handler(repository, run_id):
    return synthetic_handler(repository, run_id)
