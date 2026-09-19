"""Deterministic CPU protocol fixture. This is NOT Kronos model inference."""

import json
import random
import sys


def main():
    request = json.load(sys.stdin)
    last = float(request["prepared"]["candles"][-1]["close"])
    paths = []
    for index in range(request["config"]["sample_count"]):
        rng = random.Random((request["config"]["seed"] + index) % 2**32)
        price = last
        path = []
        for timestamp in request["prepared"]["future_timestamps"]:
            price *= 1 + rng.uniform(-0.01, 0.01)
            path.append(
                dict(
                    session=timestamp[:10],
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=100,
                )
            )
        paths.append(path)
    print(json.dumps({"paths": paths, "device": "cpu"}, allow_nan=False))


if __name__ == "__main__":
    main()
