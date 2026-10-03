"""Back up legacy SQLite data into isolated, unverified migration bundles."""

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_bundle(path: Path) -> dict:
    if path.is_symlink() or (path / "manifest.json").is_symlink():
        raise ValueError("Migration bundles must not be symlinks")
    manifest = json.loads((path / "manifest.json").read_text())
    if (
        manifest.get("version") != 1
        or manifest.get("classification") != "legacy_unverified"
        or manifest.get("mode") not in {"archive", "import"}
        or path.name != f"{manifest['mode']}-v1-{manifest.get('source_sha256')}"
        or manifest.get("files", {}).get("source.sqlite3") != manifest.get("source_sha256")
    ):
        raise ValueError("Invalid migration manifest")
    expected = {"source.sqlite3"}
    if manifest["mode"] == "import":
        expected.add("legacy.sqlite3")
    if set(manifest["files"]) != expected:
        raise ValueError("Unexpected migration bundle contents")
    for name, checksum in manifest["files"].items():
        if (path / name).is_symlink() or digest(path / name) != checksum:
            raise ValueError("Existing migration bundle failed integrity verification")
    return manifest


def migrate(source: Path, destination: Path, *, mode="archive", max_bytes=268_435_456) -> Path:
    """Never modify the source or accept a current evidence database as a destination."""
    if mode not in {"archive", "import"}:
        raise ValueError("Mode must be archive or import")
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source must be an existing regular SQLite file, not a symlink")
    if max_bytes < 1 or source.stat().st_size > max_bytes:
        raise ValueError("Source exceeds the archive size limit")
    if destination.is_symlink():
        raise ValueError("Destination must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = destination.resolve()
    deadline = time.monotonic() + 60
    with tempfile.TemporaryDirectory(prefix=".legacy-staging-", dir=destination) as staging:
        stage = Path(staging)
        backup = stage / "source.sqlite3"
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            page_size = src.execute("PRAGMA page_size").fetchone()[0]

            def progress(status, remaining, total):
                if time.monotonic() > deadline or total * page_size > max_bytes:
                    raise ValueError(
                        "Backup exceeded its time or size budget; stop writers and retry"
                    )

            with closing(sqlite3.connect(backup)) as target:
                src.backup(target, pages=128, progress=progress)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Source backup failed SQLite integrity check")
        checksum = digest(backup)
        final = destination / f"{mode}-v1-{checksum}"
        if final.exists():
            verify_bundle(final)
            return final
        count = 0
        if mode == "import":
            with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as src:
                tables = {
                    row[0]
                    for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "schema_migrations" in tables or "documents" not in tables:
                    raise ValueError("Not a supported legacy documents database; use archive mode")
                columns = {row[1] for row in src.execute("PRAGMA table_info(documents)")}
                if not {"id", "content", "metadata"} <= columns:
                    raise ValueError("Unsupported documents schema; use archive mode")
                with closing(sqlite3.connect(stage / "legacy.sqlite3")) as target:
                    with target:
                        target.execute("""CREATE TABLE legacy_records (
                            source_id TEXT PRIMARY KEY, text TEXT NOT NULL, metadata_raw TEXT,
                            content_hash TEXT NOT NULL,
                            classification TEXT NOT NULL CHECK(classification='legacy_unverified'))""")
                        for ident, text, metadata in src.execute(
                            "SELECT id, content, metadata FROM documents ORDER BY id"
                        ):
                            if (
                                not isinstance(ident, str)
                                or not isinstance(text, str)
                                or not isinstance(metadata, (str, type(None)))
                            ):
                                raise ValueError(
                                    "Unsupported legacy record types; use archive mode"
                                )
                            content_hash = hashlib.sha256(
                                json.dumps([ident, text, metadata], ensure_ascii=False).encode()
                            ).hexdigest()
                            target.execute(
                                "INSERT INTO legacy_records VALUES (?, ?, ?, ?, 'legacy_unverified')",
                                (ident, text, metadata, content_hash),
                            )
                            count += 1
        files = {p.name: digest(p) for p in stage.iterdir() if p.is_file()}
        manifest = {
            "version": 1,
            "mode": mode,
            "classification": "legacy_unverified",
            "archived_at": datetime.now(UTC).isoformat(),
            "source_sha256": checksum,
            "imported_records": count,
            "files": files,
            "notice": "Untrusted legacy data. No verified evidence or source dates inferred.",
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for path in stage.iterdir():
            path.chmod(0o600)
        # Publish only complete bundles. Existing bundles are verified, never replaced.
        try:
            os.rename(stage, final)
        except OSError:
            if not final.is_dir():
                raise
            verify_bundle(final)
        return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("data/runtime/legacy"))
    parser.add_argument("--mode", choices=["archive", "import"], default="archive")
    args = parser.parse_args()
    try:
        path = migrate(args.source, args.destination.resolve(), mode=args.mode)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        parser.exit(
            1,
            "Migration failed; check SQLite format, schema, permissions and bundle integrity. Source unchanged.\n",
        )
    print(f"Legacy-unverified bundle: {path}")


if __name__ == "__main__":
    main()
