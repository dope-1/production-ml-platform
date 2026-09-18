# Batch 2 delivery — Milestones 6–8

Application version: **0.3.0**. This is a cumulative source release through
Milestone 8, designed to upgrade the user's verified Batch 1 model without
retraining it or replacing its preprocessing implementation.

## Implemented

| Milestone | Delivered behavior |
|---|---|
| 6 — Inference | Versioned predict/explain endpoints; strict 19-field input validation; approved, hash-checked model loader; atomic snapshot reload; SHAP reconstruction; chunked CSV scoring; private prediction ledger; real HTTP benchmark |
| 7 — Monitoring | Version/cohort/time-window isolation; numeric PSI and categorical total variation; prediction drift; delayed-label metrics/calibration; sample-support guards; missing-field/error/latency metrics; dashboard and saved reports; seeded mild/moderate/severe simulations |
| 8 — Retraining | Manual/drift/performance entry points; fresh-label validation; ID/profile leakage rejection; byte-preserved holdouts; train-only CV; test left unevaluated; candidate registration/reference; champion comparison/gate; audit and resumable receipts |

Database revision 0002 adds predictions, HTTP events and monitoring reports.
Admin keys protect label attachment, snapshot saving, reload and synthetic HTTP
cohort selection. Local read/predict routes and MLflow are not public deployment
interfaces; the broader security/cloud work remains Batch 3.

## Verification executed in this workspace

The executable suite covers real six-candidate training and MLflow SQL/artifact
operations, reference publication/loading, promotion/rejection/rollback,
reconciliation, corruption checks, actual pipeline explanations across all three
model families, feature validation, CSV parity/rollback, drift thresholds, delayed
labels, missing support, cohort isolation and holdout-preserving retraining.

The real retraining test trained a new challenger in an isolated synthetic-test
registry, rejected it for insufficient improvement and verified that the champion
alias was retained. The existing lifecycle test also exercises successful
promotion and rollback under an explicitly fixture-only equality policy. Those
fixture policies are never applied to the live model.

**72 tests passed, 1 PostgreSQL test skipped; total coverage 81%.** Ruff lint,
format checks and strict mypy also passed. See `verification/batch-2-tests.txt`
for the complete executed test/coverage log.
The PostgreSQL integration test is skipped here because Docker/PostgreSQL are
unavailable. The Windows upgrade command sets `TEST_DATABASE=1` and runs that
check plus prediction/label/report CRUD through the real Docker API.

A separate cold-process verification launched a real MLflow HTTP artifact server
and Uvicorn process, loaded the real Batch 1 UCI model through a different host
URI, checked **120 prediction scores for parity**, reconstructed a SHAP explanation,
attached and retried **120 historical labels**, saved reports, reloaded the model,
and generated four isolated synthetic cohorts. Its observation database was
SQLite, explicitly not a substitute for PostgreSQL verification.

The dashboard HTTP endpoint and embedded JavaScript syntax were checked. Browser
rendering was not executed because a browser binary is unavailable in this
workspace; no screenshot is presented as proof of a rendered UI.

## Measured HTTP benchmark

`verification/batch-2-http.json` is the authoritative machine-readable evidence.
One Uvicorn worker, real HTTP requests, real RF model, SQLite prediction/event
writes, concurrency 4, 10 warmup requests excluded, 200 timed requests:

| Measurement | Observed |
|---|---:|
| Successful requests | 200 / 200 |
| Error rate | 0% |
| P50 | 81.29 ms |
| P95 | 98.53 ms |
| P99 | 108.02 ms |
| Throughput | 49.05 requests/s |

Measured on Linux x86_64, Python 3.12.14, 9 logical CPUs reported by the runtime.
This shared development runtime was also running tests; these numbers are not
isolated hardware capacity measurements. The Windows verifier records the same
measurements against the user's actual Docker/PostgreSQL stack. Its results will
vary by machine and load. The registry's in-process model latency gate is a
separate measurement, not a claim about API service latency or a cloud SLA.

## Synthetic shift evidence

Each scenario contains 600 seeded resampled training observations. Financial
limits and repayment statuses are perturbed according to the named severity;
no outcomes are invented. They are stored under separate synthetic cohorts.

| Scenario | Observed drift decision | Score PSI | Mean score |
|---|---|---:|---:|
| No shift | Stable | 0.0147 | 0.2153 |
| Mild | Stable | 0.0172 | 0.2227 |
| Moderate | Drift | 0.6672 | 0.3745 |
| Severe | Drift | 4.6623 | 0.5979 |

The mild perturbation staying below policy thresholds is an actual result, not
changed to force a desired alert. Synthetic input drift demonstrates detection;
it does not establish concept drift, label accuracy or real production performance.

## Material boundaries

- Single controller and one Uvicorn worker; explicit reload after promotion.
- No live customer data, cloud deployment or public authentication claim.
- CSV batch support; no Parquet reader in this release.
- Monitoring windows are capped at 50,000 predictions/events each.
- Retention and periodic job invocation are explicit operator/scheduler actions.
- New raw features and actual labels must be supplied separately for retraining.
- Validation is held fixed for fair comparison; repeated policy decisions still
  require independent evaluation governance before a real deployment.
- DB commit and CSV output publication are not one distributed transaction.

The source ZIP excludes secrets, environments, live state, processed datasets,
trained artifacts and generated live reports. Static, labeled verification
evidence and the pinned public UCI archive are included.
