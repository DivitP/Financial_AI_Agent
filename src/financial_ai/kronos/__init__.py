"""Kronos configuration and integrity checks, without importing ML dependencies."""

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourcePin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: HttpUrl
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: Literal["MIT"]
    license_url: HttpUrl


class ArtifactPin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["model", "tokenizer"]
    repository: str = Field(pattern=r"^NeoQuasar/Kronos-[A-Za-z0-9-]+$")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: Literal["MIT"]
    license_url: HttpUrl
    filename: Literal["model.safetensors"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    config_git_blob: str = Field(pattern=r"^[0-9a-f]{40}$")

    def cache_path(self, root: Path) -> Path:
        return root / self.role / self.revision

    def verify(self, root: Path) -> None:
        """Check local weights and configuration without deserializing either."""
        directory = self.cache_path(root)
        weight = directory / self.filename
        if not weight.is_file():
            raise ValueError(f"Missing {self.role} weights in {directory}")
        with weight.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if weight.stat().st_size != self.size_bytes or digest != self.sha256:
            raise ValueError(f"{self.role} weight integrity check failed")
        config = (directory / "config.json").read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(config)).encode() + b"\0" + config).hexdigest()
        if blob != self.config_git_blob:
            raise ValueError(f"{self.role} config integrity check failed")


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    reviewed_at: str
    source: SourcePin
    max_context: Literal[512]
    artifacts: list[ArtifactPin] = Field(min_length=2, max_length=2)


def load_manifest() -> ModelManifest:
    return ModelManifest.model_validate(
        json.loads(files(__package__).joinpath("manifest.json").read_text())
    )
