"""Actionable public failure reasons without raw provider exceptions or secrets."""

import sqlite3


def failure_reason(error: BaseException) -> str:
    from financial_ai.quotas import QuotaExceeded

    if isinstance(error, QuotaExceeded):
        return "Quota limit reached; wait for the budget to reset before retrying."
    if isinstance(error, TimeoutError):
        return "Request timed out; retry when the provider is available."
    if isinstance(error, MemoryError):
        return "Model memory exhausted; reduce context or use a smaller model before retrying."
    if isinstance(error, sqlite3.OperationalError):
        return "Storage unavailable; check database access or locks, then retry."
    if isinstance(error, (ValueError, TypeError)):
        return "Invalid or missing provider data; inspect lane coverage and retry collection."
    if isinstance(error, ConnectionError):
        return "Provider unavailable; check connectivity or select an available provider."
    return "Execution failed; inspect configured providers and retry. Partial evidence is retained."
