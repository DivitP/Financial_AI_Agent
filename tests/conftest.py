"""Offline test helpers for the legacy application."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


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
