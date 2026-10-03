FROM ghcr.io/astral-sh/uv:0.12.4 AS uv
FROM python:3.12.13-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --extra scale --no-install-project
COPY . .
RUN uv sync --locked --no-dev --extra scale \
    && useradd --uid 10001 --create-home research \
    && mkdir -p /app/data/runtime /app/model-cache \
    && chown -R research:research /app/data /app/model-cache
USER research
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/app/model-cache/huggingface MPLCONFIGDIR=/tmp/matplotlib
CMD ["uvicorn", "financial_ai.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
