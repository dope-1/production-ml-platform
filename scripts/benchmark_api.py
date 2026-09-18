"""Measure real HTTP latency and throughput, including validation and durable prediction writes."""

import argparse
import asyncio
import os
import platform
import time
from pathlib import Path

import httpx
import numpy as np

from ml_platform.core.config import Settings
from ml_platform.core.io import read_json, write_json


async def benchmark(
    url: str, payload: dict, admin_key: str, requests: int = 200, concurrency: int = 4
) -> dict:
    if not 10 <= requests <= 10000 or not 1 <= concurrency <= 64:
        raise ValueError("Use 10–10000 requests and concurrency 1–64")
    headers = {"X-Data-Cohort": "benchmark", "X-Admin-Key": admin_key}
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(
        base_url=url, timeout=30, headers=headers, limits=limits, trust_env=False
    ) as client:
        for _ in range(10):
            response = await client.post("/api/v1/predict", json=payload)
            response.raise_for_status()

        async def one() -> tuple[float, bool, str | None]:
            async with semaphore:
                start = time.perf_counter()
                try:
                    response = await client.post("/api/v1/predict", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    valid = 0 <= data["risk_score"] <= 1 and bool(data["prediction_id"])
                    return (time.perf_counter() - start) * 1000, valid, data["model_version"]
                except (httpx.HTTPError, ValueError, KeyError):
                    return (time.perf_counter() - start) * 1000, False, None

        start = time.perf_counter()
        results = await asyncio.gather(*(one() for _ in range(requests)))
        duration = time.perf_counter() - start
    elapsed = [value for value, _, _ in results]
    successes = sum(ok for _, ok, _ in results)
    return {
        "requests": requests,
        "warmup_requests": 10,
        "concurrency": concurrency,
        "successes": successes,
        "errors": requests - successes,
        "error_rate": 1 - successes / requests,
        "duration_seconds": duration,
        "throughput_rps": requests / duration,
        "latency_ms": {f"p{q}": float(np.percentile(elapsed, q)) for q in (50, 95, 99)},
        "model_versions": sorted({v for _, _, v in results if v is not None}),
        "client_environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "scope": "Loopback HTTP; includes scoring and PostgreSQL writes when using Docker.",
        "note": "Measured on this machine; no cloud SLA claim. Warmup excluded from timings.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--input", type=Path, default=Path("examples/predict.json"))
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("reports/api-benchmark.json"))
    args = parser.parse_args()
    key = Settings().admin_key
    if key is None:
        raise SystemExit("ML_ADMIN_KEY is required for the isolated benchmark cohort")
    result = asyncio.run(
        benchmark(
            args.url, read_json(args.input), key.get_secret_value(), args.requests, args.concurrency
        )
    )
    write_json(args.output, result)
    print(result)
    if result["errors"]:
        raise SystemExit("Benchmark returned failed requests; inspect API logs")


if __name__ == "__main__":
    main()
