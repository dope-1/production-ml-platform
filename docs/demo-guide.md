# Local portfolio demonstration

This demonstration uses the existing local public-data model. CloudFront account verification
was declined; Milestone 10 remains incomplete. Close unrelated tabs and hide credentials before capture. Never
show `.env`, Terraform state or secret values. The dashboard key field is masked.

## Collect current local evidence once

The reviewed 22 September capture is already included in `docs/verification/portfolio/`.
Use it with its original date. No new benchmark is needed merely to apply the documentation
update; run the command below only when you need a new measurement.

From the repository root with the configured local services running:

```powershell
docker compose ps
.\.venv\Scripts\python.exe scripts\collect_portfolio_evidence.py --benchmark
if ($LASTEXITCODE -ne 0) { throw 'Capture failed; do not publish older output files' }
```

The collector requires authentication and ready model version 1 by default. It runs the
existing benchmark once, then reads model/monitoring endpoints. It writes an allowlisted JSON
summary and two Markdown reports under `reports/portfolio/`. It does not read AWS credentials,
Terraform state or backups. Keys stay in memory. Review the outputs before publishing.
Benchmark predictions are persisted in the isolated `benchmark` cohort; no labels, training,
promotion or cloud actions are performed.

## Review sequence


Predict and explain the public example in the verification cohort:

```powershell
$headers = @{ 'X-Admin-Key' = (.\.venv\Scripts\python.exe -c "from ml_platform.core.config import Settings; print(Settings().admin_key.get_secret_value())"); 'X-Data-Cohort' = 'verification' }
$body = Get-Content examples\predict.json -Raw
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/predict -Headers $headers -ContentType application/json -Body $body
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/explain -Headers $headers -ContentType application/json -Body $body
Remove-Variable headers
```

Open `http://127.0.0.1:8000/api/v1/dashboard`, connect with the API key and select `benchmark`.
Choose `7 days` to include the 22 September capture after its default 24-hour window expires,
while the observations remain within seven days. The dashboard count may include later traffic;
do not relabel the archived report as a new capture.
Repeated inputs can cause drift; `insufficient_labels` is also valid. Do not manufacture
outcomes to make the UI green. For older verification traffic, choose a window covering its
run or show the archived reference report. Demonstrate rejection/rollback through the existing
lifecycle evidence rather than changing the live champion just for a demonstration.

## Screenshots and publication

Create `docs/screenshots/` and use `Win+Shift+S` to capture only the relevant application:

1. `dashboard-local.png`: populated cohort, model version, time window and support status.
2. `mlflow-local.png`: selected model/run, with no credentials visible.
3. `ci-green.png`: latest successful GitHub CI and its commit/run identity.

Add Markdown image links to the README after the files exist. The existing evaluation and
SHAP plots are genuine reference assets. Publish only reviewed screenshots.
Keep credentials and private account information out of captures.

After inspecting the generated aggregates, publish just the collector's three output files:

```powershell
New-Item -ItemType Directory -Force docs\verification\portfolio | Out-Null
Copy-Item reports\portfolio\evidence.json, reports\portfolio\benchmark.md, reports\portfolio\monitoring.md docs\verification\portfolio\
```

The README already links the reviewed `docs/verification/portfolio/benchmark.md` and
`monitoring.md`. Keep the declined CloudFront review and incomplete AWS deployment explicit
until a verified alternative or approved resumed deployment exists. Final validation/manifest/Git
commands are in the [portfolio checklist](milestone-11-report.md).
