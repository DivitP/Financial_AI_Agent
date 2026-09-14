"""One forecast per process: exit releases model memory even on failure."""

import contextlib
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

from financial_ai.kronos import ModelManifest


def run(request):
    manifest = ModelManifest.model_validate(request["manifest"])
    source, assets = Path(request["source"]), Path(request["assets"])
    head = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True
    )
    if head != manifest.source.revision or dirty:
        raise ValueError("Kronos source must match the clean pinned revision")
    for artifact in manifest.artifacts:
        artifact.verify(assets)
    import numpy as np
    import pandas as pd
    import torch

    config = request["config"]
    device = config["device"]
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable")
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS unavailable")
    random.seed(config["seed"])
    np.random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    if device == "cuda":
        torch.cuda.manual_seed_all(config["seed"])
        torch.backends.cudnn.benchmark = False
    spec = importlib.util.spec_from_file_location(
        "model", source / "model/__init__.py", submodule_search_locations=[str(source / "model")]
    )
    if spec is None or spec.loader is None:
        raise ValueError("Kronos model package missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules["model"] = module
    spec.loader.exec_module(module)
    pins = {a.role: a for a in manifest.artifacts}
    model = module.Kronos.from_pretrained(
        str(pins["model"].cache_path(assets)), local_files_only=True
    )
    tokenizer = module.KronosTokenizer.from_pretrained(
        str(pins["tokenizer"].cache_path(assets)), local_files_only=True
    )
    model.eval()
    tokenizer.eval()
    predictor = module.KronosPredictor(
        model, tokenizer, device=device, max_context=manifest.max_context
    )
    prepared = request["prepared"]
    columns = ["open", "high", "low", "close", "volume"]
    if all(b["amount"] is not None for b in prepared["candles"]):
        columns.append("amount")
    frame = pd.DataFrame([{c: float(b[c]) for c in columns} for b in prepared["candles"]])
    if "amount" not in columns:
        # Prevent upstream's silent OHLC-average * volume approximation.
        frame["amount"] = 0.0

    def timestamps(name):
        return pd.Series(
            pd.to_datetime(prepared[name], utc=True)
            .tz_convert(prepared["timezone"])
            .tz_localize(None)
        )

    paths = []
    for index in range(config["sample_count"]):
        seed = (config["seed"] + index) % 2**32
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if device == "cuda":
            torch.cuda.manual_seed_all(seed)
        # Upstream averages sample_count>1 internally. Request one draw at a
        # time to retain complete trajectories instead of an averaged path.
        with torch.inference_mode():
            prediction = predictor.predict(
                df=frame,
                x_timestamp=timestamps("historical_timestamps"),
                y_timestamp=timestamps("future_timestamps"),
                pred_len=len(prepared["future_timestamps"]),
                T=config["temperature"],
                top_p=config["top_p"],
                sample_count=1,
                verbose=False,
            )
        candles = []
        for timestamp, (_, row) in zip(
            prepared["future_timestamps"], prediction.iterrows(), strict=True
        ):
            candles.append(
                dict(session=timestamp[:10], **{c: float(row[c]) for c in columns if c != "amount"})
            )
        paths.append(candles)
    return {"paths": paths, "device": device}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        result = run(request)
    print(json.dumps(result, allow_nan=False))
