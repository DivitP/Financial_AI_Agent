"""FastAPI transport layer; routes depend on application use cases only."""

from financial_ai.api.app import create_app

__all__ = ["create_app"]
