# Benchmark report

## Reviewed local capture: 22 September 2026

The owner supplied the [raw aggregate evidence](verification/portfolio/evidence.json) and
[generated benchmark report](verification/portfolio/benchmark.md), captured at 06:27:41 UTC.
Health, readiness and denial of anonymous API access passed. All 200 timed requests succeeded
with zero errors, concurrency 4 and 10 excluded warmups.

| P50 | P95 | P99 | Throughput |
|---:|---:|---:|---:|
| 193.83 ms | 227.17 ms | 252.10 ms | 20.49 requests/s |

The client was Windows 10, Python 3.12.11, with 12 logical CPUs. Serving identity was
`credit-default` version `1`, run `3ed34af186ec4fe28dcbd36f5136a5f6`.
The checkout was `3d01bc99c433406b18a2bd618d3e5cb146ded1f4` with uncommitted changes;
this does not establish the running container's source revision. The owner's accompanying
Compose diagnostics identify local Docker, PostgreSQL and MLflow. Server CPU/RAM limits and
background load were not recorded, so no capacity or cloud-performance claim is made.

This serving run differs from the reference evaluation run. Keep the reference quality metrics
under their original provenance; the current capture tests serving behavior, not predictive accuracy.
The current and historical HTTP runs use different environments and database backends, so
their timing difference is not an isolated performance regression measurement.

## Recorded reference measurements

| Scope | Workload | P50 | P95 | P99 | Throughput |
|---|---|---:|---:|---:|---:|
| In-process selected random forest | 30 warmed single-row repetitions | 12.49 ms | 13.86 ms | 20.82 ms | Not measured |
| Loopback HTTP with durable SQLite writes | 200 timed requests, concurrency 4, 10 excluded warmups | 81.29 ms | 98.53 ms | 108.02 ms | 49.05 requests/s |

These are recorded reference results, not new or cloud measurements. The HTTP run completed
200/200 requests with zero errors on 17 September 2026. Sources:
[candidate.json](verification/candidate.json), [batch-2-http.json](verification/batch-2-http.json).
Both used Linux x86_64 and Python 3.12.14. The HTTP client reported 9 logical CPUs; server
hardware allocation was not fully recorded. Model workers: 2; Uvicorn workers: 1.

## Interpretation and limitations

HTTP timing includes request handling, validation, scoring and database writes. It excludes
cold-start artifact loading and warmup. The benchmark repeats one public example, not a
representative population or mixed endpoint workload. Per-request latency starts after
acquiring the client semaphore, excluding queue wait; throughput covers the whole timed batch.

The existing benchmark includes failed requests in its latency percentiles, if any. Read error
counts alongside latency. The recorded checkout commit does not establish the running container revision. Client
environment is not server capacity. There is no saturation
sweep, sustained-load study, cloud comparison or SLA claim.

## Capture the actual local Docker/PostgreSQL deployment

```powershell
.\.venv\Scripts\python.exe scripts\collect_portfolio_evidence.py --benchmark
if ($LASTEXITCODE -ne 0) { throw 'Capture failed; do not publish older output files' }
```

The collector invokes the existing benchmark once with 200 requests and concurrency 4, then
writes `reports/portfolio/benchmark.md`, monitoring and JSON evidence. It records the capture
time and observed model identity. No training, labels, promotion or AWS changes are performed.
The `benchmark` cohort stays separate from live traffic. Repeated identical inputs may trigger
drift and are not representative of real customer behavior.

The collector does not infer the database engine from HTTP responses: verify the actual
Compose services and record server CPU/RAM, Docker limits and background load before a
capacity comparison. Automatic environment information describes the client only.
If quotas return 429, let the quota window expire before one retry; keep authentication and
rate limits enabled. Preserve earlier reference results under their original measurement scope.
