"""Offline test helpers for the legacy application."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


@pytest.fixture(autouse=True)
def disable_legacy_dotenv_discovery(monkeypatch):
    """Legacy imports must not discover a developer .env through stack frames."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def isolated_budget(tmp_path):
    """Provider fixture calls use real quotas in a fresh database, not developer state."""
    from financial_ai.storage.database import Database
    from financial_ai.quotas import Quotas

    db = Database(tmp_path / "fixture-quotas.db")
    db.migrate_to_latest()
    with Quotas(db).context("fixture-run"):
        yield


@pytest.fixture
def import_main(monkeypatch: pytest.MonkeyPatch, tmp_path) -> ModuleType:
    """Import `main` with harmless test credentials and no project `.env` file."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("FMP_API_KEY", "test-fmp-key")
    for module_name in [
        "main",
        "agents.search_agent",
        "agents.fundamental_agent",
        "agents.technical_analysis_agent",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("main")


@pytest.fixture
def import_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path) -> ModuleType:
    """Import the Flask app in a temporary working directory."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("FMP_API_KEY", "test-fmp-key")
    for module_name in [
        "frontend.app",
        "main",
        "agents.search_agent",
        "agents.fundamental_agent",
        "agents.technical_analysis_agent",
        "settings",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("frontend.app")
