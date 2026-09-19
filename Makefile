UV ?= $(if $(wildcard .venv/bin/uv),.venv/bin/uv,uv)
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install install-all lint format typecheck test frontend-install frontend-lint frontend-test frontend-build check

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

.PHONY: rag-eval
rag-eval:
	$(PYTHON) -m pytest tests/test_rag_evaluation.py --no-cov -s

frontend-install:
	npm --prefix frontend/web install

frontend-lint:
	npm --prefix frontend/web run lint

frontend-test:
	npm --prefix frontend/web run test

frontend-build:
	npm --prefix frontend/web run build

check: lint format typecheck test frontend-lint frontend-test frontend-build

.PHONY: kronos-benchmark
kronos-benchmark:
	$(PYTHON) -m pytest benchmarks/kronos --no-cov -q
	$(PYTHON) -m benchmarks.kronos.run --output data/runtime/benchmarks/kronos-fixture.json
