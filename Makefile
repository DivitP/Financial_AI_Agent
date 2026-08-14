UV ?= $(if $(wildcard .venv/bin/uv),.venv/bin/uv,uv)
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install install-all lint format typecheck test frontend-lint frontend-test frontend-build check

install:
	$(UV) sync --all-groups

install-all:
	$(UV) sync --all-groups --all-extras

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

# The legacy frontend is Flask/Python, so these validate its Python source and
# render tests. They will be replaced by Node-based commands with the React UI.
frontend-lint:
	$(PYTHON) -m ruff check frontend

frontend-test:
	$(PYTHON) -m pytest tests/test_frontend.py

frontend-build:
	$(PYTHON) -m compileall -q frontend

check: lint format typecheck test frontend-lint frontend-test frontend-build
