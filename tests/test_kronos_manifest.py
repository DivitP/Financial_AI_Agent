import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from financial_ai.kronos import load_manifest
from settings import Settings


def test_manifest_loads_without_ml_imports():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from financial_ai.kronos import load_manifest; import sys; m=load_manifest(); assert len(m.artifacts)==2; assert 'torch' not in sys.modules; assert 'huggingface_hub' not in sys.modules",
        ],
        check=True,
    )
    manifest = load_manifest()
    assert {item.role for item in manifest.artifacts} == {"model", "tokenizer"}
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert not any(dep.startswith(("torch", "einops")) for dep in project["dependencies"])
    assert any(dep.startswith("torch") for dep in project["optional-dependencies"]["kronos"])


def test_integrity_rejects_missing_or_corrupted_weights(tmp_path):
    pin = load_manifest().artifacts[0]
    with pytest.raises(ValueError, match="Missing"):
        pin.verify(tmp_path)
    directory = pin.cache_path(tmp_path)
    directory.mkdir(parents=True)
    data = b"offline fixture"
    (directory / pin.filename).write_bytes(data)
    with pytest.raises(ValueError, match="integrity"):
        pin.verify(tmp_path)
    config = b"{}"
    (directory / "config.json").write_bytes(config)
    fixture = pin.model_copy(
        update={
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "config_git_blob": hashlib.sha1(b"blob 2\0" + config).hexdigest(),
        }
    )
    fixture.verify(tmp_path)
    (directory / "config.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="config integrity"):
        fixture.verify(tmp_path)


def test_settings_leave_kronos_disabled_and_reject_unreviewed_model():
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert not settings.enable_kronos and not settings.kronos_allow_downloads
    with pytest.raises(ValueError, match="manifest"):
        Settings(ENABLE_KRONOS=True, KRONOS_MODEL="unknown", _env_file=None)  # type: ignore[call-arg]
