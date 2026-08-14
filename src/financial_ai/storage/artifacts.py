"""Content-addressed local artifacts for permitted raw responses and exports."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class FileSystemArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def put_bytes(self, content: bytes, *, category: str, suffix: str = "") -> str:
        if not category.replace("_", "").isalnum():
            raise ValueError("artifact category must be alphanumeric or underscore")
        digest = hashlib.sha256(content).hexdigest()
        artifact_id = f"{category}_{digest}"
        path = self._path_for(artifact_id, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, path)
        return artifact_id

    def put_text(self, content: str, *, category: str, suffix: str = ".txt") -> str:
        return self.put_bytes(content.encode("utf-8"), category=category, suffix=suffix)

    def read_bytes(self, artifact_id: str, *, suffix: str = "") -> bytes:
        return self._path_for(artifact_id, suffix).read_bytes()

    def exists(self, artifact_id: str, *, suffix: str = "") -> bool:
        return self._path_for(artifact_id, suffix).exists()

    def _path_for(self, artifact_id: str, suffix: str) -> Path:
        category, _, digest = artifact_id.rpartition("_")
        if (
            not category
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("invalid artifact id")
        return self.root / category / digest[:2] / f"{digest}{suffix}"
