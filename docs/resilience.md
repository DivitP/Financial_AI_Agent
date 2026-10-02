# Offline failure and recovery checks

Run `uv run pytest tests/test_resilience.py --no-cov` or `make check`.
Fixtures require no provider keys, internet, model downloads or GPU.

The suite injects provider timeouts, malformed JSON, empty/wrong-shaped lane
responses, outages, graph timeouts, model memory exhaustion, SQLite write locks,
an abrupt worker subprocess exit, and SSE reconnects after failure.

Required collection lanes and graph nodes must all succeed for a run to be
`completed`. A failure leaves the run `failed` with successful snapshots or
checkpoints retained: this is recoverable partial research, not a success claim.
There is no new `partial` wire status. Inspect per-lane errors/checkpoints and
retry failed research through the existing API. Graph resume reuses completed
nodes. Empty or non-object outputs cannot masquerade as valid structured data;
field-level financial validation still belongs to provider schemas.

Local worker recovery requeues interrupted work within its attempt budget and
skips persisted completed steps. Abrupt exit is tested with `os._exit` in a real
child process, not by editing status rows. Recovery is for a stopped worker;
do not invoke local recovery against another active worker. Side effects must
remain idempotent because an interrupted unfinished step may execute again.

A lock before job acquisition raises an explicit storage error and leaves the
job pending, with no attempt consumed. Retry after the lock is released; this
does not claim that every prolonged database outage can persist its own error.
Terminal job failures expose safe recovery guidance, not raw exception strings.
Exhausted retries remain failed. SSE resumes strictly after the last event ID,
including failed terminal events, without replaying already received events.

Optional Kronos failures remain separately visible and do not invalidate usable
core research. Existing Kronos tests cover subprocess timeout/termination,
invalid outputs, uncached failures and optional-lane degradation. These tests
are fault injection, not live-provider reliability or real GPU OOM benchmarks.
