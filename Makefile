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
	$(PYTHON) -m benchmarks.coverage

.PHONY: coverage-report
coverage-report:
	$(PYTHON) -m benchmarks.coverage

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

.PHONY: frontend-a11y
frontend-a11y:
	npm --prefix frontend/web run test:a11y

.PHONY: performance
performance:
	$(PYTHON) -m benchmarks.system
	npm --prefix frontend/web run test:e2e -- performance.spec.ts

check: lint format typecheck test frontend-lint frontend-test frontend-build

.PHONY: release-eval
release-eval:
	$(PYTHON) -m benchmarks.release

.PHONY: local-up local-down local-smoke
local-up:
	docker compose up --build --detach --wait --wait-timeout 180

local-down:
	docker compose down

local-smoke:
	docker compose exec -T api python -m financial_ai.ops smoke

.PHONY: kronos-benchmark
kronos-benchmark:
	$(PYTHON) -m pytest benchmarks/kronos --no-cov -q
	$(PYTHON) -m benchmarks.kronos.run --output data/runtime/benchmarks/kronos-fixture.json
