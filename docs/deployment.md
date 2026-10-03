# Free-first deployment and operations

This is the entry point for new operators. Commands run from the repository root
unless stated otherwise. No paid provider, managed database, cloud account or GPU
is required for the supported offline setup. Your machine, electricity, disk and
network still have costs; “free tier” is not unlimited service or redistribution
permission. Provider references below were checked October 3, 2026; recheck account
limits before enabling live calls.

## Choose an operating mode

| Mode | Prerequisites | What actually runs |
| --- | --- | --- |
| Local development | Git, Python 3.12/3.13, uv, Node 22/npm | SQLite API, React UI, offline tests; no automatic live worker |
| Local Compose demo | Docker with Compose v2 | Web, API, Redis worker, Postgres; explicitly synthetic demo data |
| Scaled self-hosting | Own hardware, same containers, trusted worker factory | Shared jobs/storage; live collection requires assembling and validating the worker integration |

There is **not yet a bundled end-to-end live research worker**. Provider adapters,
analysis nodes and APIs exist, but adding FMP/Groq keys does not wire them together.
Do not describe a demo or an API health response as verified live financial research.
There is no brokerage or trading execution in these deployment paths.

## 1. Local-only setup

Install Git, Python 3.12/3.13, Node 22 (includes npm), and uv using their official
installers: [uv](https://docs.astral.sh/uv/getting-started/installation/),
[Node](https://nodejs.org/en/download). Reopen the terminal after installation.
Then, in your cloned checkout:

```bash
uv --version
node --version
npm --version
uv sync --locked --all-groups
npm --prefix frontend/web ci
```

An `.env` file is optional for offline operation. For live-provider development,
copy `.env.example` **only if `.env` does not already exist**, then edit locally:

```bash
test -e .env || cp .env.example .env
```

Keep `ENABLE_GROQ`, `ENABLE_FMP`, `ENABLE_LOCAL_LLM`, and `ENABLE_KRONOS` false
initially. Never paste credentials into commits, reports, screenshots or logs.
Environment variables override `.env`; remove stale shell exports when diagnosing
unexpected settings. Start two terminals at the repository root:

```bash
# Terminal 1: SQLite API (migrations run automatically at startup)
uv run uvicorn financial_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000
# Terminal 2: development UI, same-origin /api proxy to port 8000
npm --prefix frontend/web run dev -- --host 127.0.0.1
```

Open http://localhost:5173 and http://localhost:8000/docs. Verify
`curl --fail http://127.0.0.1:8000/ready`. `/` on the API is intentionally not the UI.
The default database is `data/runtime/financial_ai.db`. Do not start multiple
local worker owners against it. Jobs submitted without a configured worker can
remain pending; the local job-run endpoint alone is not live data collection.

For an end-to-end **offline** research demonstration, use Compose below or run
`uv run pytest tests/test_vertical_research.py --no-cov`. For contributor checks:

```bash
make check
cd frontend/web
npx playwright install chromium
cd ../..
make release-eval
```

Release artifacts are ignored under `data/runtime/release/`; see
[evaluation thresholds and manual sign-off](release-evaluation.md).

## 2. One-command container startup

```bash
docker compose up --build --detach --wait --wait-timeout 180
docker compose exec -T api python -m financial_ai.ops smoke
docker compose ps
```

Open http://localhost:8080. No `.env` keys are injected into this default stack.
The smoke command creates a saved, labelled synthetic run. Read
[local Compose details](local-compose.md) for non-root users, health checks,
volume paths, pinned release tags and limitations. Initial downloads require
internet; subsequent demo operation needs no provider access. Docker build/boot
has not been verified in the implementation environment because Docker is absent.

## 3. Optional free providers and models

Paid fallback is never required. Missing coverage must remain visible. Consult
[provider/licensing decisions](data/provider-policy.md) before storing, displaying,
exporting or redistributing data; public accessibility is not a redistribution grant.

| Source | Setup and free-first boundary | When unavailable |
| --- | --- | --- |
| SEC | No key; use an identifying contact User-Agent on `SharedHttpClient`, then pass that client to `SecFilingCollector`. There is no `SEC_API_KEY` setting. | Keep filings/statements unavailable and retry conservatively. |
| yfinance | Base dependency, no Yahoo API key. Review source terms and personal-use restrictions. | Retain old as-of data with freshness warnings, or mark absent. |
| OpenBB | `uv sync --locked --extra openbb`; explicitly select the yfinance extension/provider. Core install does not include every provider. | Use permitted direct adapters or show missing extension; never silently select paid sources. |
| GDELT / approved RSS / company IR | Public sources; configure approved feed URLs and explicit download-host allowlist in the calling adapter. There is no universal news-key setting. | Use fewer sources, disclose coverage; search snippets are not evidence. |
| FMP | Optional free account/key; set `FMP_API_KEY` and `ENABLE_FMP=true` only after checking endpoint entitlement. | Prefer SEC for filings/facts, permitted market sources for prices; estimates may simply be absent. |
| Groq | Optional free account/key; set `GROQ_API_KEY`, `ENABLE_GROQ=true`, and a currently available supported `GROQ_MODEL`. | Keep data collection independent of LLMs; disable chat or explicitly select a local model. |
| Local model | Install/run Ollama locally, download a reviewed model, install `--extra local-llm`, set `ENABLE_LOCAL_LLM=true`, `LOCAL_LLM_BASE_URL` and `LOCAL_LLM_MODEL`. Disable Groq first. | Use deterministic analyses; hardware/RAM limits are real. No automatic fallback is promised. |

SEC fair access limits aggregate traffic to 10 requests/second; stay well below
that across all processes and identify your application. See
[SEC access policy](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits).
FMP currently advertises 250 calls/day on its free plan; access is endpoint-specific
and bandwidth is also limited. Check the [FMP dashboard](https://site.financialmodelingprep.com/developer/docs/dashboard)
and [plan details](https://site.financialmodelingprep.com/pricing-plans).
Groq allowances vary by model/account; use the [account limits and headers](https://console.groq.com/docs/rate-limits),
not a hardcoded assumption about free throughput. Do not enable billing to make
an unavailable feature appear supported.

For SEC, a live worker constructs its client with
`SharedHttpClient(user_agent="YourApp contact@your-real-domain.example")` using
your **actual** contact address, not that placeholder. `DOCUMENT_ALLOWED_HOSTS`
is a JSON array; add only reviewed public source hosts. Do not disable SSRF checks
or permit private addresses to fix a blocked download. OpenBB AGPL compatibility
and provider redistribution review remain prerequisites for network deployment,
not obligations resolved by installing the extra.

### Optional model acquisition

The base application never downloads weights. An extra installs Python packages,
not weights. Repeating `uv sync` without the same extras may remove those extras;
keep the selected install command in your deployment notes.

For Ollama, install it using the [official local setup](https://docs.ollama.com/quickstart),
open its desktop app or run `ollama serve` in a separate terminal if no server is
already running. To acquire the model named in this repository's `.env.example`:

```bash
ollama pull qwen3:8b
ollama list
uv sync --locked --extra local-llm
```

Review that model's license and memory needs before download. Set
`ENABLE_LOCAL_LLM=true`, `ENABLE_GROQ=false`, `LOCAL_LLM_MODEL=qwen3:8b` and
`LOCAL_LLM_BASE_URL=http://127.0.0.1:11434` locally, then restart the API. This is
local inference, not an Ollama cloud subscription. Inside a container, loopback
refers to that container, not your host: supply a reachable, trusted Ollama endpoint
explicitly in your override; the default Compose demo does not include Ollama.

For Kronos, follow the pinned source checkout commands in [Kronos setup](kronos.md),
then deliberately download the manifest-pinned artifacts (internet/disk required):

```bash
uv sync --locked --extra kronos
uv run python - <<'PY'
from pathlib import Path
from huggingface_hub import hf_hub_download
from financial_ai.kronos import load_manifest
from settings import get_settings
root = Path(get_settings().kronos_cache_dir)
for pin in load_manifest().artifacts:
    for filename in (pin.filename, "config.json"):
        hf_hub_download(repo_id=pin.repository, revision=pin.revision,
                        filename=filename, local_dir=pin.cache_path(root))
    pin.verify(root)
print("Pinned artifacts verified; inference is still opt-in.")
PY
```

Only then consider `ENABLE_KRONOS=true`; retain CPU as the initial device and
experimental labels until out-of-sample promotion gates pass. Preserve upstream
licenses. `KRONOS_ALLOW_DOWNLOADS=true` alone does nothing. Container cache mounts
do not install optional dependencies or copy a host source checkout automatically.
For local embeddings use a reviewed, revision-pinned sentence-transformer directory
and the explicit `LocalEmbeddings`/`ResearchIndex` wiring in [retrieval setup](retrieval.md).
There is no turnkey embedding-download or index-rebuild CLI yet.

## 4. Scaled self-hosting on your own hardware

The default `compose.yml` already exercises Postgres/Redis, but only with the demo
handler. The separate `compose.scale.yml` is an advanced API/worker profile:

1. Implement/test a trusted packaged `module:function(repository, run_id)` factory
   returning a synchronous step handler for `collect`, `analyze`, `report`.
   Keep calls bounded/idempotent, persist evidence before findings, and raise or
   record failed research when required collection fails. Start with
   `financial_ai.workflow.demo:handler` **only** to verify infrastructure.
2. In the launching shell, set `POSTGRES_PASSWORD` to a new locally managed secret
   (URL-encode it in a connection URI if needed) and `WORKER_HANDLER_FACTORY` to
   that trusted factory. The advanced file interpolates the password into its URI;
   use a strong URL-safe value. Do not reuse the demo password on a shared host.
3. Run `docker compose -f compose.scale.yml up --build --detach`. This is a
   separate stack definition, not an override of `compose.yml`. It has no web
   service; use the local UI proxy or a separately configured same-origin web server.
4. Verify `/ready`, worker logs, successful saved output and failure/retry cases.
   Scale workers only after that validation:
   `docker compose -f compose.scale.yml up --detach --scale worker=2`.

The advanced profile must receive reviewed provider variables through an explicit
override; setting them in a developer `.env` does not automatically pass them to
containers. API and workers must share database/Redis configuration, runtime
artifacts and model assets. API startup migrates schema: perform initial startup
with one API owner, then add workers. Do not run competing migration processes.
The advanced file lacks the default stack's full health/startup hardening; adapt
it before operational use rather than treating it as a public deployment template.

Neither profile includes user authentication or internet-facing TLS. Keep loopback
bindings and use your own authenticated TLS reverse proxy before considering shared
access. Match `ALLOWED_HOSTS` and exact `ALLOWED_BROWSER_ORIGINS`, retain security
headers, disable proxy buffering for SSE, and never expose Redis/Postgres publicly.
No free cloud hosting SLA is assumed. See [security boundaries](security.md).

## 5. Backups and restore drills

Stop API/workers before a coordinated backup so database, artifacts and indexes
represent the same point in time. Back up configuration separately in encrypted
storage; never print credentials. Save release revision, lockfiles and schema version
with the backup. Keep multiple generations off the source disk if possible.

### SQLite (after stopping local processes)

This uses the configured path, refuses Postgres and refuses to overwrite a backup:

```bash
uv run python - <<'PY'
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from settings import get_settings
s = get_settings()
assert s.deployment_profile == "local", "Use the Postgres procedure"
source = s.database_path.resolve()
assert source.is_file(), "Configured source database does not exist"
folder = Path("data/runtime/backups") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
folder.mkdir(parents=True, exist_ok=False)
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
    with sqlite3.connect(folder / "research.sqlite3") as dest:
        src.backup(dest)
        assert dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print(folder)
PY
```

Also copy configured artifact/export/source-document directories while stopped;
a relational backup alone cannot recover filesystem content. For a drill, copy
the backup to a **new** runtime directory, set `FINANCIAL_AI_DATABASE_PATH` to
that copy and `PERSIST_DIR` to its companion copied artifacts, then start one API.
Check integrity, run counts, old as-of reports and exact evidence links. Never
restore over the only working database. Do not copy a live SQLite file without
its transactional backup mechanism.

### Default Compose Postgres/runtime

The following shell sequence stops writers, creates a unique private directory,
and dumps the local demo database plus runtime files; it does not delete volumes:

```bash
docker compose stop api worker web
mkdir -p data/runtime/backups
backup_dir=$(mktemp -d ./data/runtime/backups/backup-XXXXXXXX)
chmod 700 "$backup_dir"
docker compose exec -T postgres pg_dump -U research -d research -Fc > "$backup_dir/research.dump"
docker compose run --rm --no-deps --entrypoint tar api -C /app/data/runtime -cf - . > "$backup_dir/runtime.tar"
docker compose exec -T postgres pg_restore --list < "$backup_dir/research.dump"
docker compose up --detach --wait
```

Check **every command's exit status**; do not accept an empty/failed dump as a
backup. Move that directory to your private backup location, never commit it.
Redis AOF persists in its volume, but relational jobs/outbox are authoritative;
a SQL dump is not a queue-consistent restore plan. Retain the Redis volume during
routine upgrades and test delivery/recovery separately after disaster recovery.
Model weights can be re-downloaded from pinned revisions; back up irreplaceable
local models separately. Runtime archives may include secrets from bad historical
inputs: encrypt and restrict access even though current logging is secret-safe.

Restore into a **new database/stack**, not the running research database. For an
isolated drill on the default Postgres service, with writers still stopped:

```bash
docker compose exec -T postgres createdb -U research research_restore
docker compose exec -T postgres pg_restore -U research -d research_restore --exit-on-error < "$backup_dir/research.dump"
docker compose exec -T postgres psql -U research -d research_restore -c 'SELECT count(*) FROM research_runs;'
```

`createdb` must succeed first; if that name already exists, choose a new name,
never silently reuse/overwrite it. Restore the runtime archive into a **new**
volume/directory and verify ownership UID 10001. Point a stopped test API at the
new DB and runtime volume using an explicit Compose override. Validate old reports,
evidence, pending-job recovery and exports before any intentional production switch.

## 6. Migrations, upgrades and rollback

For old Flask/vectorstore data, use [legacy archive and quarantine migration](legacy-migration.md)
before upgrading. Uncited legacy reports must never become verified evidence.

1. Record revision and selected extras; stop all writers and take a tested backup.
2. Install with the new committed locks or rebuild images. Do not edit the lockfile
   on the deployment host to make an incompatible install succeed.
3. Start one API; `Database.migrate_to_latest()` runs at startup. Check `/ready`
   and schema version before starting additional workers.
4. Run the demo smoke check **only in a demo stack** and release evaluation in
   a test environment. Reopen a pre-upgrade saved run; verify as-of dates unchanged.
5. On failure, stop the new processes and restore the pre-upgrade DB/artifacts
   into new storage with the old code/locks. Do not run old code blindly against
   a newer schema. Downgrade methods are tested but can drop newer data; they are
   not a data-preserving rollback substitute. No automatic downgrade is performed.

## 7. Caches, quotas and observability

HTTP and serialized snapshot caches are bounded/process-local; restart their
owning API/worker to clear them. Revision checks keep snapshot reads current.
Do not delete the source database to fix a stale browser: refresh UI, compare
as-of times, and inspect [cache metrics](performance.md) first.

Kronos `forecasts.sqlite3` is a disposable inference cache; stop all readers before
moving it to a dated backup location for recreation. Keep pinned model assets,
source evidence and persisted model-run/backtest records. Chroma/FTS are derived
indexes, but rebuilding requires the original approved source text; follow
[retrieval instructions](retrieval.md), not a blanket runtime-directory wipe.

[Quotas](quotas.md) lists exact setting names. Local defaults are safety budgets,
not your provider account balance. A 429/`Retry-After` is not permission to retry
forever. Per-run call/article/model budgets survive retries; wait only helps
time-window limits, not an exhausted per-run budget. Inspect failed lanes, choose
less work or deliberately adjust configuration. Do not rotate credentials or
reset quota tables to bypass provider restrictions. Retain failure/audit records.
Use [the data-health console](settings-console.md) and [observability](observability.md)
to distinguish queue delay, slow provider calls, stale caches and model latency.

## 8. Troubleshooting and handoff checklist

| Symptom | Check / recovery |
| --- | --- |
| `uv` / `npm` not found | Install prerequisite, reopen terminal, verify PATH; npm ships with Node. |
| API `/` or favicon returns 404 | Use UI port 5173/8080 or API `/docs`/`ready`; not a server crash. |
| Research stays pending | Local mode has no automatic live worker; check worker factory/queue, not API keys alone. |
| Compose starts but data says demo | Expected default; do not present it as real data. A live handler is a separate integration task. |
| `docker` missing / daemon unavailable | Install/start Docker with Compose v2; Python tests cannot validate container boot. |
| SEC 403 / provider 429 | Real contact User-Agent, allowed host, account quota, cooldown and request budget; no unlimited retries. |
| Invalid model / 401 | Recheck active provider flag, model ID and account key locally; never post the key in an issue. |
| Database locked / permission denied | Stop competing writers; inspect exact volume/path and UID ownership. Do not erase the DB. |
| Worker unhealthy / job interrupted | Inspect logs and dependencies; bounded retry/reclaim applies. Do not call local recovery while another owner runs. |
| Missing model / OOM | Verify manifest files/source; reduce context/sample count or use smaller/CPU model. Keep core data collection available. |
| SSE reconnects / no progress | Same-origin proxy, buffering off, long read timeout, Last-Event-ID preserved; inspect API/worker readiness. |
| Blank/unsupported report or Q&A | Check evidence, failed lanes and citation validation; do not fill missing facts with model guesses. |

Handoff requires setup commands, chosen flags/extras, secret location (not values),
hardware/storage paths, verified backup restore, configured worker factory,
release report, provider/license review and explicit known gaps. A new contributor
can deploy the no-paid-service demo; complete live research and public production
deployment remain separate, explicitly documented integration/security work.
