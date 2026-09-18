# Production ML Platform

A reproducible credit-default ML system with versioned data, MLflow experiments,
gated promotion, real-time and batch inference, monitoring and controlled
retraining. **Implemented: Milestones 1–9.** Cloud deployment and final polish remain
Milestones 10–11. This is an engineering demonstration,
not a system approved for real lending decisions.

## Milestone 9 upgrade — verified Batch 2 checkout

Copy only the patch's included files into your existing project, then run in VS Code:

```powershell
.\.venv\Scripts\python.exe scripts\upgrade_milestone9.py
```

This enables API/admin keys, runs focused checks and rebuilds only the API. Your
model, database credentials and saved observations are retained. The dashboard now
requires `ML_API_KEY` from `.env`; paste its value into the key field and click
**Connect**. Select **verification** or **benchmark** to see earlier test traffic.
[Milestone 9 guide](docs/milestone-9-guide.md) covers keys, CI/security scans and the
next steps. [Verification evidence](docs/milestone-9-report.md) records local results
and checks still requiring Docker/GitHub Actions.

## Upgrade from your verified Batch 1 — Windows / VS Code

Copy the contents of this archive's `production-ml-platform` directory into your
existing `E:\Projects\production-ml-platform`, replacing source files. Keep your
existing `.env`, `.venv`, `.state`, processed data, model reports and Docker
volumes. The archive excludes those private/generated files. Keep the folder
name so Compose continues using your existing volumes.

Start Docker Desktop, open the project in VS Code and run:

```powershell
.\.venv\Scripts\python.exe scripts\upgrade_batch2.py
```

This installs pinned dependencies, rebuilds the services, migrates PostgreSQL,
adds a verified monitoring reference to your approved model and loads it into
the API. It runs software checks, isolated champion/challenger tests, real
service verification, delayed-label checks, drift simulations and a benchmark.
Your live champion is retained. A local admin key is generated in `.env`.

| Interface | Local URL |
|---|---|
| Monitoring dashboard | http://127.0.0.1:8000/api/v1/dashboard |
| Interactive API | http://127.0.0.1:8000/docs |
| MLflow experiments and registry | http://127.0.0.1:5000 |

Select **verification**, **benchmark** or a **synthetic** cohort in the dashboard
to inspect the verification run. The live cohort remains empty until you use it.
Reports are written to `reports/batch-2-verification.json`,
`reports/api-benchmark.json` and `reports/simulation/`.

[Complete Batch 2 guide](docs/batch-2-guide.md) covers prediction payloads, batch
CSV scoring, labels, monitoring windows, retraining, model reload and rollback.
[Verification report](docs/batch-2-report.md) separates tests run here from the
Docker/PostgreSQL checks performed on your machine.

## Use the prediction API

```powershell
$headers = @{ 'X-API-Key' = (.\.venv\Scripts\python.exe -c "from ml_platform.core.config import Settings; print(Settings().api_key.get_secret_value())") }
$body = Get-Content examples\predict.json -Raw
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/predict -Headers $headers -ContentType application/json -Body $body
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/explain -Headers $headers -ContentType application/json -Body $body
Remove-Variable headers
```

The input contract contains the actual 19 UCI financial features. Responses
include score, class, model version, UTC timestamp, request ID and prediction ID.
The same fitted preprocessing pipeline runs in training and inference. The
explanation includes its output space and verifies that contributions reconstruct
the score; it does not make a causal claim.

```powershell
.\.venv\Scripts\python.exe -m ml_platform.ops batch --input examples\batch-input.csv --output reports\batch-scores.csv
.\.venv\Scripts\python.exe -m ml_platform.ops monitor --hours 24
.\.venv\Scripts\python.exe -m ml_platform.ops simulate
```

Batch scoring is vectorized. Monitoring combines numeric PSI, categorical total
variation, score/class drift, HTTP metrics and delayed-label quality/calibration.
Feature payloads and customer IDs are absent from the monitoring ledger. Feature
bins and scores still deserve protection and retention limits.

## Controlled retraining

```powershell
.\.venv\Scripts\python.exe -m ml_platform.ops retrain --labeled-data data\incoming\labeled.csv --trigger manual
```

Drift and performance modes require fresh live evidence. Retraining requires a
separate validated dataset of new features and actual labels, preserves both
holdouts byte-for-byte, performs grouped CV, registers a challenger and applies
the existing promotion gate. Rejected challengers retain the champion. Simulation
cohorts never trigger live retraining. After a promotion/rollback, explicitly
reload the API or run `docker compose restart ml-api`; serving pins an approved
snapshot until then. Read the guide for the labeled-data schema and safeguards.

## Fresh installation

Use Python 3.12 and Docker Desktop/Engine with Compose v2 or later. Create `.venv`
with your installed Python 3.12 interpreter, then create `.env` **once**:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import secrets; Path('.env').write_text(Path('.env.example').read_text().replace('ML_DB_PASSWORD=', 'ML_DB_PASSWORD=' + secrets.token_hex(24)))"
.\.venv\Scripts\python.exe scripts\upgrade_milestone9.py --configure-only
.\.venv\Scripts\python.exe scripts\upgrade_and_verify.py
.\.venv\Scripts\python.exe scripts\upgrade_batch2.py
```

The first script bootstraps Milestones 1–5 with inference disabled until a model
exists. A successful promotion is required before Batch 2. Review a REJECT result;
do not weaken gates merely to complete a demo. Do not regenerate credentials for
an initialized PostgreSQL volume. On Linux use `.venv/bin/python`.

## Training and registry

```bash
python -m ml_platform.cli prepare
python -m ml_platform.cli train
python -m ml_platform.cli register
python -m ml_platform.cli promote --version 1
python -m ml_platform.cli status
python -m ml_platform.cli rollback --version 1 --reason "Investigating the newer model's deployment behavior"
```

Use the version actually returned by registration. All mutations must share the
same persistent controller directory. Pending writes require explicit
`python -m ml_platform.cli reconcile`. Global `--tracking-uri`, `--config` and
`--control-dir` flags precede the subcommand. The default host tracking URI is
http://127.0.0.1:5000. The serving container uses the internal Docker URI and a
read-only controller mount. [Registry operations](docs/registry.md) describes the
single-controller boundary and integrity checks.

## Data and methodology

The pinned UCI Default of Credit Card Clients archive contains 30,000 historical
Taiwan observations; source and CC BY attribution are in `data/README.md`.
Financial-profile groups remain together in deterministic train/validation/test
partitions. Model inputs exclude identifiers, targets and demographic audit
fields; the saved pipeline adds three financial ratios.

Six configurations span logistic regression, random forest and LightGBM.
Train-only grouped CV average precision selects a candidate, with a simplicity
tolerance; validation selects a recall-constrained threshold. The initial training
run evaluates only the chosen candidate on test. Retraining leaves test unevaluated.
No test metric determines promotion. This historical dataset does not establish
present-day or temporal lending validity.

[Model card](docs/model_card.md) and `docs/verification/` contain actual evidence.
Batch 1 model latency and Batch 2 HTTP latency measure different scopes. The
included HTTP reference uses SQLite observations; the Windows verifier benchmarks
your actual Docker API and PostgreSQL. No cloud SLA is claimed.

## Verification and boundaries

```powershell
.\.venv\Scripts\python.exe scripts\verify_batch2.py
```

This reruns verification without reinstalling or rebuilding. An optional
`--skip-software-checks` resumes only service checks after software checks have
already succeeded. `docker compose logs -f ml-api mlflow` helps diagnose startup.
`docker compose down` preserves volumes; `--volumes` deletes stored data.

Published ports bind to loopback. API data/prediction routes require a key and
mutations require admin authorization. MLflow remains a private local interface.
MLflow stores metadata/artifacts in its Docker volume; PostgreSQL holds the
prediction ledger and monitoring reports. CI validates software, dependencies,
source security, secrets, container controls and image vulnerabilities. The separate
manual workflow validates models and benchmarks serving. See [Security](SECURITY.md)
for current boundaries; cloud deployment is Milestone 10.

See [architecture](docs/architecture.md), [data pipeline](docs/data_pipeline.md),
[responsible AI](docs/responsible_ai.md), and [Batch 2 guide](docs/batch-2-guide.md).
