# Release checklist

Use a copy of this checklist in a release issue. Unchecked items are not completed
work. Record revision, date, reviewer, intended mode (synthetic demo, local live,
or scaled), configuration without secrets, and links to reviewed artifacts.
This documentation change does not declare a release ready.

## Reproducible engineering gates

- [ ] From a clean checkout, install with `uv sync --locked --all-groups` and
  `npm --prefix frontend/web ci`; record Python, uv, Node/npm and OS versions.
- [ ] Run `make check` and `git diff --check`; retain results.
- [ ] Review [split coverage](coverage.md) reports: replacement must meet 87%
  lines and 69% branches independently. Retain legacy/shared-setting measurements
  separately and investigate per-file gaps rather than blending totals.
- [ ] Install Chromium using the README command, then run `make release-eval`.
  Attach the reviewed `quality.md`/`quality.json`, revision and exclusions.
  Use the exact thresholds in [release evaluation](release-evaluation.md), not
  a historical passing test count. A dirty worktree result is not proof of the
  tagged artifact; rerun against the candidate revision.
- [ ] Review desktop/mobile screenshots and complete keyboard/screen-reader flows
  in [accessibility QA](accessibility-qa.md). Capture alone is not visual approval.
- [ ] Confirm CI quality, deployment-profile and secret-scan jobs pass for the
  candidate revision. Local evaluation does not run every CI service/security gate.
- [ ] For scaled claims, run real Postgres/Redis integration tests with isolated
  `TEST_POSTGRES_URL`/`TEST_REDIS_URL`; skipped service tests do not qualify.
- [ ] On a clean Docker-capable machine, run the README Compose startup and smoke
  commands. Verify readiness, worker delivery, persistence across restart and
  the synthetic-data label. Record outcome; never call the demo live research.

## Product claims and data quality

- [ ] Audit each README feature against its implementation and linked tests.
  Mark unconnected modules as optional/integration work rather than completed
  live features. Update [architecture](architecture/README.md) when wiring changes.
- [ ] Record replacement parity and outstanding [retirement gates](replacement-workflow.md).
  Keep legacy code until gates pass; archive/quarantine old data before removal.
- [ ] For live-mode claims, validate permitted SEC/Yahoo/RSS requests separately
  with real operator contact configuration, recording retrieval time and exact
  source links. Do not put credentials or restricted responses in fixtures.
- [ ] Demonstrate provider failure, incomplete data, cancellation/retry and saved
  partial reports. Do not silently relabel incomplete coverage as success.
- [ ] Verify units, currencies, reporting periods, stale-data warnings, citation
  traceability, and exported claims against persisted report versions.
- [ ] Confirm ETF views omit corporate-only fields and disclose unavailable holdings.
- [ ] Verify LLM-disabled collection; test configured Q&A models separately for
  citation enforcement and unsupported questions. Fixture prompts do not certify
  live model answer quality.
- [ ] Leave Kronos disabled/experimental unless the optional runtime, pinned
  artifacts, complete input contract, real-weight measurements and documented
  out-of-sample promotion gates pass. Record limitations and failed results too.
  No BUY/SELL commands or uncalibrated confidence claims.

## Source rights, costs and security

- [ ] Recheck official provider terms and account quotas on the release date.
  Record review date, provider/extension versions, attribution, display, export,
  retention and indexing permissions in the [provider policy](data/provider-policy.md).
  Historical quota examples are not current account guarantees.
- [ ] Demonstrate a useful permitted no-paid-provider path with explicit gaps;
  confirm no silent paid fallback and bounded retries/budgets.
- [ ] Review project, OpenBB/extensions and model licenses; record AGPL notices,
  corresponding-source offer and applicable deployment/legal review. Source-code
  licenses do not license third-party data.
- [ ] Inspect tracked files and release artifacts for secrets, private documents,
  model weights and runtime databases. Run the configured secret scan.
- [ ] Reassess dependency advisories (including `npm --prefix frontend/web audit`)
  and Python dependency risks; record fixes or explicit risk acceptance with owner
  and expiry. A passing lint suite is not a vulnerability audit.
- [ ] Confirm loopback binding for local use, approved hosts/origins, bounded
  downloads and security headers. Public deployment requires authentication,
  HTTPS and a separately reviewed gateway; none is supplied by browser CSRF checks.
- [ ] Review logs, screenshots and exports before sharing; raw evidence is not
  automatically safe or licensed for redistribution.

## Operations and decision

- [ ] Exercise backup and restore to a separate database; record schema version,
  compatible application revision, artifact/index handling and restore outcome.
- [ ] Test migrations and document rollback using the retained backup and prior
  compatible revision. Never downgrade over the only copy of evidence.
- [ ] Document cache/model cleanup, quota exhaustion and interrupted-worker
  recovery for the selected mode; follow [operations](deployment.md).
- [ ] Record **approved**, **preview only**, or **blocked**, with reviewer/date,
  unresolved risks, excluded modes, and follow-up owners. Do not check a gate
  merely because its instructions exist.
