"""Offline guards against runtime drift between installs, CI and containers."""

import json
from pathlib import Path
import tomllib

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]


def test_python_runtime_contract():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    default = (ROOT / ".python-version").read_text().strip()
    assert default == "3.12.13"
    assert project["project"]["requires-python"] == ">=3.12,<3.14"
    assert lock["requires-python"].replace(" ", "") == ">=3.12,<3.14"
    assert project["tool"]["ruff"]["target-version"] == "py312"
    assert project["tool"]["mypy"]["python_version"] == "3.12"
    assert f"FROM python:{default}-" in (ROOT / "Dockerfile").read_text()
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["quality"]
    assert job["strategy"]["matrix"]["python"] == [default, "3.13"]
    assert job["env"]["UV_PYTHON"] == "${{ matrix.python }}"
    python = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-python@"))
    assert python["with"]["python-version"] == "${{ matrix.python }}"
    for workflow, job_name in (
        (ci, "deployment-profiles"),
        (
            yaml.safe_load((ROOT / ".github/workflows/kronos-benchmark.yml").read_text()),
            "fixture-regression",
        ),
    ):
        steps = workflow["jobs"][job_name]["steps"]
        setup = next(s for s in steps if s.get("uses", "").startswith("actions/setup-python@"))
        assert setup["with"]["python-version-file"] == ".python-version"


def test_node_runtime_contract():
    default = (ROOT / ".nvmrc").read_text().strip()
    package = json.loads((ROOT / "frontend/web/package.json").read_text())
    lock = json.loads((ROOT / "frontend/web/package-lock.json").read_text())
    assert default == "22.14.0"
    assert package["engines"] == {"node": f">={default} <23", "npm": ">=10 <11"}
    assert lock["packages"][""]["engines"] == package["engines"]
    assert f"FROM node:{default}-" in (ROOT / "deploy/web.Dockerfile").read_text()
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = ci["jobs"]["quality"]["steps"]
    setup = next(s for s in steps if s.get("uses", "").startswith("actions/setup-node@"))
    assert setup["with"]["node-version-file"] == ".nvmrc"


def test_setup_documents_identify_runtime_defaults():
    for path in ("README.md", "AGENTS.md", "docs/deployment.md", "docs/development-runtimes.md"):
        text = (ROOT / path).read_text()
        assert "3.12.13" in text and "22.14.0" in text and "npm 10" in text


def test_legacy_dotenv_cannot_enable_live_providers(tmp_path, monkeypatch):
    import os
    from dotenv import load_dotenv

    monkeypatch.delenv("ENABLE_GROQ", raising=False)
    fixture = tmp_path / ".env"
    fixture.write_text("ENABLE_GROQ=true\n")
    assert load_dotenv(fixture) is False
    assert "ENABLE_GROQ" not in os.environ
