"""Check local guide links and execute its SQLite backup against disposable data."""

import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/deployment.md"


def test_deployment_guide_links_and_python_examples():
    text = GUIDE.read_text()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if not target.startswith("https://"):
            assert (GUIDE.parent / target).is_file(), target
    snippets = re.findall(r"uv run python - <<'PY'\n(.*?)\nPY", text, re.S)
    assert len(snippets) == 2
    for snippet in snippets:
        compile(snippet, "deployment.md", "exec")


def test_documented_sqlite_backup_preserves_data(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE evidence(id TEXT PRIMARY KEY, content TEXT)")
        db.execute("INSERT INTO evidence VALUES ('fixture', 'saved as-of evidence')")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "settings.get_settings",
        lambda: SimpleNamespace(deployment_profile="local", database_path=source),
    )
    snippets = re.findall(r"uv run python - <<'PY'\n(.*?)\nPY", GUIDE.read_text(), re.S)
    backup = next(s for s in snippets if "src.backup(dest)" in s)
    exec(compile(backup, "deployment.md", "exec"), {})
    copies = list((tmp_path / "data/runtime/backups").glob("*/research.sqlite3"))
    assert len(copies) == 1
    for path in (source, copies[0]):
        with sqlite3.connect(path) as db:
            assert (
                db.execute("SELECT content FROM evidence").fetchone()[0] == "saved as-of evidence"
            )
