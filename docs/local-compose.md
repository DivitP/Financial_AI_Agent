# Local Docker Compose environment

Requires Docker Engine/Desktop with Compose v2 supporting `up --wait`, internet
for the initial image/package download, and free loopback ports 8080 and 8000.
No host Python, Node, API keys, GPU or model weights are required. From a clone:

```bash
docker compose up --build --detach --wait --wait-timeout 180
# Equivalent with make installed: make local-up
docker compose exec -T api python -m financial_ai.ops smoke
```

Open http://localhost:8080 (React UI) or http://localhost:8000/docs (API).
**The default worker is an OFFLINE DEMO, not live financial research.** The UI
identity, report and exports explicitly label invented financial figures. The
default handler uses the shared synthetic collector and research pipeline for
collection, calculations, a persisted chart, indexed evidence and a saved report.
The smoke command creates a synthetic AAPL run and checks the web proxy → API →
Redis worker → Postgres path, including price history, chart and report output.
It does not certify live-provider coverage. Do not use demo output for investment
decisions. Supported labels are AAPL, MSFT, NVDA, SPY and QQQ; unknown symbols fail
without live fallback. Evidence destinations use the web origin localhost:8080.

## Services, storage and security

- Postgres 17 stores research/jobs/evidence, Redis stores durable queue delivery,
  the API handles requests, the worker consumes jobs, and non-root nginx serves
  the production React build with same-origin API/SSE proxying.
- Every service runs as a named/numeric non-root user with dropped capabilities
  and no-new-privileges. Only loopback web/API ports are published; database and
  Redis ports are internal. This is single-user local development, not a shared
  server, authenticated multi-user installation or internet deployment.
- The database password `local-demo-only` is intentionally public and local-only.
  No developer `.env` is passed to containers or copied into image layers.
  External providers, LLMs and Kronos are disabled explicitly. Supply a reviewed
  Compose override with a trusted packaged `WORKER_HANDLER_FACTORY` and only
  necessary environment variables to run live integrations. Never mount `.env`
  or credentials into the frontend image.
- Named volumes `postgres`, `redis`, `runtime` and `model-cache` preserve state
  across rebuilds/restarts. `/app/model-cache` is writable by UID 10001, with HF
  and Kronos cache paths inside it. No weights are bundled or auto-downloaded.
  Installing optional model extras and verified assets remains a separate opt-in
  build; mounting a cache alone does not enable inference.
- Web health checks static serving; API readiness checks SQL and Redis; worker
  health requires a completed queue iteration. Its 650-second freshness window
  accommodates bounded 540-second research runs (it is not an instant crash
  detector). Failed workers remain observable through status/logs.
- API initialization performs migrations before readiness. Worker startup waits
  for the API so migrations do not race on a fresh database. Dependency ordering
  follows [Compose health-check conditions](https://docs.docker.com/compose/how-tos/startup-order/).
- Python and npm use committed lockfiles, images have explicit release tags,
  and frontend builds are multi-stage. Tags are not immutable digests: bit-for-bit
  supply-chain reproducibility still requires reviewed digest pins. No guarantee
  is made that rebuilding years later yields identical OS package layers.

## Operations

```bash
docker compose ps
docker compose logs --tail=100 api worker web
docker compose restart worker
docker compose down
docker compose up --detach --wait
```

`down` preserves all named volumes. **Do not add `--volumes` unless you intend to
permanently delete local research, queue state and model caches.** Back up named
volumes before upgrades. Do not reuse an incompatible old database volume;
inspect permissions/versions first instead of deleting data as a troubleshooting
shortcut. Avoid printing `docker compose config` after adding secret overrides.

The earlier `compose.scale.yml` remains an advanced separate configuration with
a required custom handler; do not merge it with this default file.

## Verification status

Offline tests validate Compose structure, demo execution, health checks and
secret exclusion. PyYAML is an explicit development dependency for Compose
structure checks (already present transitively; runtime dependencies unchanged).
Container startup must additionally be checked with the two
commands above on Docker, including stop/start and saved-run reopening. Docker
is not available in the implementation environment; a clean-machine image build
and boot have **not** been verified here. Do not treat static tests as a container
startup certification.
