# Supported development runtimes

Use Python 3.12.13 and Node 22.14.0 with npm 10 by default.

| Runtime | Supported range | Reproducible default |
| --- | --- | --- |
| Python | 3.12 and 3.13 | 3.12.13 in `.python-version` and the API Dockerfile |
| Node | 22.x, at least 22.14.0 | 22.14.0 in `.nvmrc` and the web Dockerfile |
| npm | 10.x | npm bundled with the pinned Node installation |

These are compatibility choices for this repository, not claims that the pinned
patches are the latest security releases. Review patch updates and advisories
before release. Python 3.11/3.14 and other Node majors are not supported by this
development contract. Historical benchmark runtime records are not setup instructions.

From the repository root, select Node with `nvm install` then `nvm use` if you use
nvm. Otherwise install the version in `.nvmrc` with your preferred runtime manager.
Reopen your terminal and verify `node --version` and `npm --version`; a different
Homebrew/Conda/system runtime earlier in PATH can override your selection.

```bash
uv sync --locked --all-groups
npm --prefix frontend/web ci
uv run python --version
node --version
npm --version
make check
```

uv reads `.python-version` automatically. To exercise the other supported Python
minor without replacing the default `.venv`, use a separate environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv-313 uv sync --locked --all-groups --python 3.13
UV_PROJECT_ENVIRONMENT=.venv-313 uv run --locked --python 3.13 pytest
```

Both Python minors run locked installation and quality checks in CI. `UV_PYTHON`
in the CI matrix explicitly overrides `.python-version`. The scaled-service and
Kronos fixture jobs use the default file; web checks use `.nvmrc`. Docker retains
explicit base-image pins because Docker `FROM` does not read these version files.
Offline contract tests compare all these declarations to prevent drift.

The Python minimum changed from 3.11 to the already documented 3.12; `uv.lock`
must be regenerated without an upgrade request. The npm lock's root engines must
match `package.json`. No application dependency upgrade is intended by this change.
Locked installs download dependencies when absent; automated application tests
remain fixture-based with no provider keys or live financial requests.

## Validation record (2026-11-06)

On macOS arm64, locked development installs succeeded with Python 3.12.13 and
3.13.14. The Python 3.13 suite passed with 290 tests and seven skips (six
unconfigured Postgres/Redis service cases and one optional Chroma case); typing
also passed. Legacy dotenv discovery is disabled by a test-only fixture so a
developer's local configuration cannot enable providers during those tests.

Node 22.14.0 with npm 10.9.2 completed `npm ci`, all 37 frontend tests and the
Vite production build. Docker base-image alignment is checked statically; images
were not rebuilt as part of this runtime check. npm reported nine dependency
advisories; runtime alignment does not remediate those dependencies. Review them
separately before release rather than applying a forced upgrade here.
