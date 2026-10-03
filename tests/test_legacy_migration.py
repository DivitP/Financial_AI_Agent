import json
import sqlite3

import pytest

from financial_ai.storage.legacy_migration import migrate, verify_bundle


def legacy(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE documents(id TEXT PRIMARY KEY, content TEXT, metadata TEXT)")
        db.execute(
            "INSERT INTO documents VALUES ('old', 'Uncited BUY claim <script>bad()</script>', 'not valid JSON')"
        )


@pytest.mark.parametrize("mode", ["archive", "import"])
def test_repeatable_backed_up_and_isolated(tmp_path, mode):
    source = tmp_path / "vectorstore.db"
    legacy(source)
    original = source.read_bytes()
    new_evidence = tmp_path / "financial_ai.db"
    with sqlite3.connect(new_evidence) as db:
        db.execute("CREATE TABLE evidence(id TEXT PRIMARY KEY, content TEXT)")
        db.execute("INSERT INTO evidence VALUES ('new', 'verified data')")
    current = new_evidence.read_bytes()
    result = migrate(source, tmp_path / "archive", mode=mode)
    assert migrate(source, tmp_path / "archive", mode=mode) == result
    assert source.read_bytes() == original
    assert new_evidence.read_bytes() == current
    manifest = verify_bundle(result)
    assert manifest["classification"] == "legacy_unverified"
    with sqlite3.connect(result / "source.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    if mode == "import":
        with sqlite3.connect(result / "legacy.sqlite3") as db:
            row = db.execute(
                "SELECT text, metadata_raw, classification FROM legacy_records"
            ).fetchone()
            assert row == (
                "Uncited BUY claim <script>bad()</script>",
                "not valid JSON",
                "legacy_unverified",
            )
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
                ("legacy_records",)
            ]


def test_changed_records_get_new_bundle_and_tampering_is_rejected(tmp_path):
    source = tmp_path / "old.db"
    legacy(source)
    first = migrate(source, tmp_path / "archive", mode="import")
    with sqlite3.connect(source) as db:
        db.execute("UPDATE documents SET content='different uncited report'")
    second = migrate(source, tmp_path / "archive", mode="import")
    assert first != second
    assert verify_bundle(first)["imported_records"] == 1
    (second / "legacy.sqlite3").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        migrate(source, tmp_path / "archive", mode="import")


def test_failed_import_never_publishes_partial_bundle(tmp_path):
    source = tmp_path / "modern.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE schema_migrations(version INTEGER)")
    destination = tmp_path / "archive"
    with pytest.raises(ValueError, match="supported legacy"):
        migrate(source, destination, mode="import")
    assert list(destination.iterdir()) == []
    archived = migrate(source, destination)
    assert json.loads((archived / "manifest.json").read_text())["mode"] == "archive"
    with pytest.raises(ValueError, match="size"):
        migrate(source, destination, max_bytes=1)
    with pytest.raises(ValueError, match="existing"):
        migrate(tmp_path / "missing.db", destination)


def test_backup_includes_committed_wal_records(tmp_path):
    source = tmp_path / "wal.db"
    legacy(source)
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO documents VALUES ('wal', 'committed in WAL', '{}')")
        writer.commit()
        bundle = migrate(source, tmp_path / "archive", mode="import")
        with sqlite3.connect(bundle / "legacy.sqlite3") as imported:
            assert imported.execute("SELECT count(*) FROM legacy_records").fetchone()[0] == 2
