# Milestones 6–8: run and operate

This release builds on an approved Batch 1 model. Python 3.12, the existing
virtual environment, Docker Desktop and the existing project folder are used.
Security hardening and cloud deployment are Milestones 9–11.

## Upgrade in Windows / VS Code

1. Copy the archive's `production-ml-platform` contents into
   `E:\Projects\production-ml-platform`, replacing source files.
2. Keep `.env`, `.venv`, `.state`, `data/processed`, `reports/model` and the Docker
   volumes. The archive excludes these generated or private files. Keep the same
   directory name so Compose finds the existing volumes.
3. Open that folder in VS Code, start Docker Desktop and run:

```powershell
.\.venv\Scripts\python.exe scripts\upgrade_batch2.py
```

The script installs pinned packages, generates a local admin key if needed,
rebuilds services, applies Alembic revision 0002 and publishes a checksummed
monitoring reference from the approved model's exact original training split.
It then loads the approved model into the API and runs lint, formatting, types,
tests, real HTTP/PostgreSQL checks, simulations and an HTTP benchmark. The
retraining tests use isolated temporary registries; they do not retrain or
replace your live champion. Commands stop on failure.

Open:

- Dashboard: http://127.0.0.1:8000/api/v1/dashboard
- Interactive API: http://127.0.0.1:8000/docs
- MLflow: http://127.0.0.1:5000

The live dashboard is initially empty. Select **verification**, **benchmark**,
or one of the explicitly synthetic cohorts to inspect the verification run.
An empty live window is reported as insufficient evidence, not as healthy model
performance. The selector never mixes model versions or cohorts.

To rerun validation after an interrupted upgrade:

```powershell
.\.venv\Scripts\python.exe scripts\verify_batch2.py
```

After software checks have already passed, `--skip-software-checks` reruns only
the real services, simulations and benchmark. Inspect
`reports/batch-2-verification.json`, `reports/api-benchmark.json` and
`reports/simulation/simulation.json`.

## Real-time predictions and explanations

The actual model uses the UCI financial schema, not invented income or debt
fields. `examples/predict.json` contains a real historical example with exactly
19 inputs. Identifiers, labels and demographic audit fields are not accepted by
these endpoints. Missing values, non-integers, unknown fields and out-of-range
values fail with HTTP 422.

```powershell
$body = Get-Content examples\predict.json -Raw
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/predict -ContentType application/json -Body $body
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/explain -ContentType application/json -Body $body
```

Responses include `prediction`, `risk_score`, `model_version`, `request_id`,
`prediction_id` and UTC `timestamp`. Each prediction ID is unique even if a caller
reuses a request ID. A prediction is returned only after its database write
succeeds. A database failure returns 503.

Explanations expose all 22 transformed-feature contributions, their baseline,
output space and a reconstruction check. Random-forest contributions are in
probability space; logistic-regression and LightGBM contributions are in log-odds.
The linear implementation uses exact independent-feature SHAP; trees use
TreeExplainer's training-path background. They describe associations, not causes
or reasons to approve/deny credit. An explanation also records the scored request.

## Vectorized CSV scoring

CSV input must have `customer_id` and exactly the 19 financial columns. This
release supports CSV; Parquet is not implemented. The scorer processes chunks
through the fitted pipeline without sending per-row HTTP requests.

```powershell
.\.venv\Scripts\python.exe -m ml_platform.ops batch --input examples\batch-input.csv --output reports\batch-scores.csv
```

Output contains IDs, score, class, version, UTC prediction timestamp and the IDs
needed for delayed-label attachment. Customer IDs stay in the local output CSV;
they are not stored in the monitoring database. Invalid late chunks roll back
all prediction records and leave any existing output file intact. Database
commit and final filesystem publication cannot form one distributed transaction;
if output publication fails after commit, inspect the job ID in the ledger before
retrying. CSV chunks default to 2,000 rows; the ID deduplication set grows with
input size, so extremely large files need partitioning.

## Labels, monitoring and retention

`POST /api/v1/labels` requires `X-Admin-Key` from `.env`. Use Swagger's header
field or a client that reads this value without putting it into source control.
Payload:

```json
{
  "labels": [{
    "prediction_id": "<32-character ID returned by predict>",
    "actual_label": 1,
    "observed_at": "2026-09-17T18:00:00+00:00"
  }]
}
```

Provide the real observation timestamp after the prediction, with a timezone.
Unknown IDs fail, identical retries are idempotent and conflicting values or
timestamps are rejected. A label batch is transactional, and PostgreSQL row
locks serialize competing updates. Do not manufacture outcomes for live rows.
Historical UCI labels used by the verifier are isolated in `verification`.

```powershell
.\.venv\Scripts\python.exe -m ml_platform.ops monitor --cohort live --hours 24
.\.venv\Scripts\python.exe -m ml_platform.ops simulate
.\.venv\Scripts\python.exe -m ml_platform.ops purge --older-than-days 90
```

`monitor` saves a report in PostgreSQL and `reports/monitoring/latest.json`.
The dashboard can refresh reports; the protected
`POST /api/v1/monitoring/snapshot` endpoint saves one. History shows saved windows
with their model versions. `GET /api/v1/monitoring` accepts `hours`, `cohort` and an
optional timezone-aware `end` for prior prediction windows. Labels are evaluated
as of the report creation time, which is recorded explicitly. Purging is an
explicit operator command; no background retention job is installed.

Numeric drift uses train-defined quantile bins and PSI (moderate ≥0.20, severe
≥0.50). Repayment-status categories use total variation (moderate ≥0.15, severe
≥0.30). Prediction drift requires PSI ≥0.20 plus a material mean-score or
positive-rate change. A drift trigger requires three changed features or material
prediction drift. These are visible demonstration policies, not universal
statistical thresholds. No significance-only trigger is used.

Drift requires 100 predictions. Performance requires 100 labels, at least 10 of
each class, and 50% window coverage. Reports include ROC-AUC, average precision
(PR-AUC), precision, recall, F1, accuracy, Brier score, calibration bins and ECE.
A drop vs validation of more than 0.05 AUC/AP, 0.10 recall, or a Brier increase of
more than 0.05 triggers investigation/retraining eligibility. Label selection and
maturity can bias these metrics. Insufficient labels never imply good performance.

Monitoring retains coarse feature-bin indices, scores, versions, timestamps and
latency. These remain potentially sensitive financial observations; they are not
claimed to be anonymous. Raw financial payloads and protected demographic fields
are absent from the prediction ledger. Missing-feature rates count HTTP attempts,
including rejected requests. HTTP percentiles, request rate and error rates cover
predict/explain attempts; vectorized batch rows are excluded from HTTP statistics.
`/metrics` exposes Prometheus counters/histograms and the loaded model version.

Windows are bounded to 50,000 prediction rows and 50,000 HTTP events; larger
windows fail explicitly and require a shorter interval. This is a local-scale
monitor, not a streaming warehouse.

## Retrain and compare a challenger

Supply a CSV with all canonical training columns (including customer ID,
demographic audit fields and `default`) plus `prediction_timestamp` and
`label_observed_at`. Both timestamps must include a timezone. Labels must follow
predictions, be non-future and no more than 90 days old. At least 100 new rows and
both target classes are required. The upstream data owner is responsible for
joining actual features and observed outcomes; binned monitoring logs deliberately
cannot reconstruct a training dataset.

```powershell
.\.venv\Scripts\python.exe -m ml_platform.ops retrain --labeled-data data\incoming\labeled.csv --trigger manual
.\.venv\Scripts\python.exe -m ml_platform.ops retrain --labeled-data data\incoming\labeled.csv --trigger drift
.\.venv\Scripts\python.exe -m ml_platform.ops retrain --labeled-data data\incoming\labeled.csv --trigger performance
```

The commands are the job entry points. Invoke them manually or from an external
scheduler after data ingestion; no unattended retraining daemon is installed.
Drift/performance modes compute fresh monitoring evidence from **live** records
and skip when the trigger or sample support is absent. Synthetic and verification
cohorts cannot activate these modes. Manual mode represents an explicit operator
request; no command invents labels or acquires private data automatically.

New customer IDs may not overlap any original partition. New predictor profiles
may not overlap either protected holdout. The original train data are extended;
validation/test CSVs remain byte-identical. All preprocessing/CV stays train-only.
Retraining does not score the protected test set. It trains the six candidate
configurations, chooses by grouped CV, selects the threshold on validation,
registers the challenger, prepares its reference, and invokes the existing gate
against the current champion on the same validation cohort.

A rejection retains the production alias. A promotion requires all absolute,
regression, fairness-diagnostic, size and latency gates and the configured AP
improvement. Gate settings are never relaxed by the operator script. Receipt
files and the controller audit journal record the decision, source checksum,
trigger, run/version and metrics. Completed rejected jobs can be replayed without
retraining. Concurrent retraining jobs use a controller lock; registry mutations
retain the original journal/reconciliation protections.

The controller records each version's dataset path for subsequent jobs. You may
supply `--dataset` explicitly; it must match the champion. Repeated reuse of one
validation cohort can still overfit policy decisions over time. A real deployment
needs a refreshed, independently governed evaluation cohort before such a claim.

## Load the promoted model or roll back

The API pins a verified snapshot at startup. It does not contact MLflow on every
prediction, and registry changes do not silently switch an in-flight request.
After promotion or rollback, call `POST /api/v1/models/reload` with `X-Admin-Key`,
or restart the API:

```powershell
docker compose restart ml-api
```

Read `/api/v1/model` to confirm the served version. A failed reload leaves the
last verified snapshot running. On a cold start without a verified model/reference,
`/health` stays live but `/ready` and inference return 503. Pending registry
operations block new model loads until `python -m ml_platform.cli reconcile`.
The serving container reads the host controller directory through a read-only
mount; its internal `http://mlflow:5000` URI does not overwrite the host identity.

For rollback, use the existing controlled command with an actually approved
version and meaningful reason, then reload/restart the API. If the older version
has no reference yet, publish it from its exact original dataset first. Keep
MLflow and the API on the provided loopback bindings; this batch is not a public,
authenticated multi-tenant deployment.
