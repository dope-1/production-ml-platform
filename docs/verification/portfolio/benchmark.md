# Current local benchmark

Captured: 2026-09-22T06:27:41.128133+00:00

Model version: 1; MLflow run: `3ed34af186ec4fe28dcbd36f5136a5f6`.

200 timed requests; concurrency 4; 10 excluded warmups.

| Metric | Measured value |
|---|---:|
| Successes | 200 |
| Errors | 0 |
| Throughput | 20.49 requests/s |
| P50 | 193.83 ms |
| P95 | 227.17 ms |
| P99 | 252.10 ms |

Client environment:

```json
{
  "platform": "Windows-10-10.0.19045-SP0",
  "python": "3.12.11",
  "processor": "Intel64 Family 6 Model 165 Stepping 2, GenuineIntel",
  "logical_cpus": 12
}
```

Scope: warm local loopback HTTP with repeated public example inputs. Per-request timing excludes semaphore queue wait. Server hardware, database backend and Docker resource allocation need operator confirmation. This is not a saturation study, cloud result or SLA.
