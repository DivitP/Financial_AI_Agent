import contextlib
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from financial_ai.kronos import ArtifactPin, load_manifest
from financial_ai.kronos.inference import InferenceConfig, LocalKronosProvider
from financial_ai.kronos import worker
from test_kronos_preprocessing import bar, prepare


@pytest.fixture
def candles():
    return prepare([bar(d, 50) for d in [3, 4, 8, 9]])


def provider(tmp_path, **config):
    return LocalKronosProvider(
        enabled=True,
        assets=tmp_path / "assets",
        source=tmp_path / "source",
        cache=tmp_path / "cache.sqlite3",
        config=InferenceConfig(**config),
    )


def test_worker_cpu_fixture_loads_verified_assets_and_local_timestamps(
    tmp_path, monkeypatch, candles
):
    calls = []
    monkeypatch.setattr(
        worker.subprocess,
        "check_output",
        lambda cmd, **kw: load_manifest().source.revision if "rev-parse" in cmd else "",
    )
    monkeypatch.setattr(ArtifactPin, "verify", lambda self, root: calls.append(self.role))
    torch = SimpleNamespace(
        manual_seed=lambda seed: calls.append(seed),
        use_deterministic_algorithms=lambda enabled: calls.append(enabled),
        set_num_threads=lambda n: None,
        inference_mode=contextlib.nullcontext,
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)

    class Model:
        @classmethod
        def from_pretrained(cls, path, **kw):
            assert kw == {"local_files_only": True}
            return cls()

        def eval(self):
            pass

    class Predictor:
        def __init__(self, model, tokenizer, **kw):
            assert kw == {"device": "cpu", "max_context": 512}

        def predict(self, **kw):
            assert kw["x_timestamp"].dt.hour.tolist() == [16] * 4
            assert kw["df"]["amount"].tolist() == [0] * 4
            return pd.DataFrame([dict(open=50, high=50, low=50, close=50, volume=100)] * 2)

    module = SimpleNamespace(Kronos=Model, KronosTokenizer=Model, KronosPredictor=Predictor)
    monkeypatch.setattr(worker.importlib.util, "module_from_spec", lambda spec: module)
    monkeypatch.setattr(
        worker.importlib.util,
        "spec_from_file_location",
        lambda *a, **kw: SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None)),
    )
    monkeypatch.setitem(sys.modules, "model", module)
    p = provider(tmp_path)
    monkeypatch.setattr(p, "_execute", worker.run)
    assert not calls  # construction does not load models
    result = p.forecast(candles)
    assert result["device"] == "cpu"
    assert result["model_version"] == load_manifest().artifacts[0].revision
    assert result["candles"][0]["close"] == "50.0"
    assert calls[:2] == ["model", "tokenizer"]
    count = len(calls)
    assert p.forecast(candles)["cache_hit"]
    assert len(calls) == count
    p.config = InferenceConfig(seed=12)
    assert not p.forecast(candles)["cache_hit"]
    for device in ["cuda", "mps"]:
        p.config = InferenceConfig(device=device)
        with pytest.raises(ValueError, match="unavailable"):
            p.forecast(candles)


def test_subprocess_timeout_failure_and_invalid_output_are_not_cached(
    tmp_path, monkeypatch, candles
):
    p = provider(tmp_path, timeout_seconds=0.1)
    monkeypatch.setattr(
        p, "_worker_command", lambda: [sys.executable, "-c", "import time; time.sleep(10)"]
    )
    with pytest.raises(TimeoutError, match="terminated"):
        p.forecast(candles)
    p.config = InferenceConfig()
    monkeypatch.setattr(
        p, "_worker_command", lambda: [sys.executable, "-c", "raise RuntimeError('private detail')"]
    )
    with pytest.raises(RuntimeError, match="verify optional") as exc:
        p.forecast(candles)
    assert "private detail" not in str(exc.value)
    monkeypatch.setattr(
        p,
        "_worker_command",
        lambda: [sys.executable, "-c", 'print(\'{"candles": [], "device": "cpu"}\')'],
    )
    with pytest.raises(ValueError, match="sessions"):
        p.forecast(candles)
    with contextlib.closing(sqlite3.connect(p.cache)) as db:
        assert db.execute("SELECT count(*) FROM forecasts").fetchone()[0] == 0


def test_disabled_lazy_import_and_cache_expiry(tmp_path, monkeypatch, candles):
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from financial_ai.kronos.inference import LocalKronosProvider; "
            "assert 'torch' not in sys.modules; assert 'model' not in sys.modules",
        ],
        check=True,
    )
    p = provider(tmp_path, cache_ttl_seconds=0)
    p.enabled = False
    with pytest.raises(ValueError, match="disabled"):
        p.forecast(candles)
    assert not p.cache.exists()
    p.enabled = True
    result = {
        "candles": [
            dict(session=t.date().isoformat(), open=50, high=50, low=50, close=50, volume=10)
            for t in candles.future_timestamps
        ],
        "device": "cpu",
    }
    script = (
        "import os; assert os.environ['HF_HUB_OFFLINE']=='1'; print("
        + repr(json.dumps(result))
        + ")"
    )
    monkeypatch.setattr(p, "_worker_command", lambda: [sys.executable, "-c", script])
    assert not p.forecast(candles)["cache_hit"]
    assert not p.forecast(candles)["cache_hit"]


def test_source_integrity_and_input_validation(tmp_path, monkeypatch, candles):
    p = provider(tmp_path)
    monkeypatch.setattr(worker.subprocess, "check_output", lambda *a, **kw: "modified")
    monkeypatch.setattr(p, "_execute", worker.run)
    with pytest.raises(ValueError, match="clean pinned"):
        p.forecast(candles)
    with pytest.raises(ValueError, match="increase"):
        p.forecast(candles.model_copy(update={"future_timestamps": candles.historical_timestamps}))
    for options in [
        {"seed": -1},
        {"device": "invalid"},
        {"timeout_seconds": 0},
        {"temperature": float("nan")},
    ]:
        with pytest.raises(ValueError):
            InferenceConfig.model_validate(options)
