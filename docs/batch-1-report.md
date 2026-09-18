# Batch 1 completion report — Milestones 2–5

Status: implemented and exercised locally. Windows/Docker verification of this
updated release is pending the user's one-command check. No Milestone 6 work
has started. The user already verified the original Milestone 1 on Windows.

## Implemented components
- M2: real UCI download/import, bounded archive reads, source checksum pin,
  strict schema/type/null/range/category/ID checks, data manifests, stable grouped
  train/validation/test splits, per-file integrity verification, packaged financial
  feature transformation. No synthetic fallback exists in the demo path.
- M3: logistic baseline, random forest and LightGBM; six logged configurations;
  grouped train-only CV; validation threshold selection; test-on-selected-candidate;
  reproducibility metadata, evaluation/calibration plots, SHAP and subgroup reports.
- M4: actual MLflow experiments, nested runs, parameters, metrics, environment/
  dataset/configuration metadata, sklearn artifacts with custom pipeline code,
  HTTP artifact proxy and a persistent local tracking service in Compose.
- M5: version registration, candidate/production aliases, evidence and artifact
  hash checks, source/feature checks, deterministic absolute/champion gates,
  rejection reasons, approved-only rollback, local file locking, fsynced audit
  events, write-ahead records and explicit crash reconciliation.

## Verification actually executed
| Check | Actual result |
|---|---|
| Python environment | Linux container, Python 3.12.14 |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Strict mypy | Passed, 31 source files |
| pytest | 44 passed, 1 skipped, 22 warnings; 26.52 seconds |
| Statement coverage | 85% overall, including unexercised host CLI branches |
| pip check | No broken requirements |
| YAML parsing | Compose and both CI workflow files parsed |
| Full 30,000-row UCI run | Six model configurations trained and logged |
| MLflow HTTP health/UI document | HTTP 200; visual UI interaction not claimed |
| HTTP artifact upload/download | Passed against an actual MLflow server |
| Default promotion gate on real data | PROMOTE |
| Production artifact integrity/load | Passed |
| Rollback/rejection/tampering/crash recovery | Passed in isolated real MLflow E2E tests |
| Docker runtime/build | Not executable here: Docker CLI/daemon unavailable |
| PostgreSQL integration | One test skipped here; included in the Windows verifier |
| GitHub-hosted workflows | Authored, not run remotely |

The test suite uses explicit synthetic fixtures only for automated tests. Demo
metrics in model_card.md and docs/verification are from the real UCI dataset.
No mocked MLflow success is claimed. Full pytest output is bundled.

Commands included uv dependency installation/lock compilation, editable project
installation, ruff check ., ruff format --check ., mypy, pytest --cov=ml_platform
--cov-report=term-missing, and pip check. A temporary subprocess harness started
MLflow with --serve-artifacts, exercised its HTTP health/UI, trained the real data,
registered/promoted the result and loaded the approved artifact. The equivalent
user-facing workflow is scripts/verify_batch.py, called by upgrade_and_verify.py.

## Failures fixed and remaining limitations
An early audit intent call had a duplicate action argument; it was fixed and
rollback/crash-recovery tests rerun successfully. An HTTP startup probe initially
timed out while its worker initialized; startup retry handling in the temporary
harness was corrected and the complete HTTP run passed. Dependency compatibility
was pinned to NumPy <2.3 and SciPy <1.16 for the selected sklearn version.

Remaining warnings originate in Starlette/AnyIO, MLflow/Pydantic/datetime and SHAP
interfaces. They are visible in test output, not suppressed. There are no test
failures. No cloud deployment, load benchmark, live scoring endpoint or drift
monitoring is claimed. Runtime latency is an in-process reference measurement.
The registry is a local single-controller design, with trusted writers and no
public authentication. MLflow's local metadata DB is SQLite; the API uses
PostgreSQL. A cloud/multi-writer deployment requires stronger storage/locking and
access controls in later milestones.

## Windows handoff
Copy this complete source tree over the existing project, preserving .env/.venv
and the same Compose project directory. Start Docker Desktop and run:

```powershell
.\.venv\Scripts\python.exe scripts\upgrade_and_verify.py
```

Expected: all 45 tests pass with no PostgreSQL skip, services healthy, MLflow runs
visible, and a recorded promotion/rejection decision. A rejection retains the
champion and must be investigated rather than bypassed. Exact latency and model
metrics may vary by environment. The script creates reports/batch-verification.json.
No cloud account or API key is required. Internet is needed for dependencies and
container images; the public raw archive is bundled and checksum-verified.

Next batch: Milestones 6–8 (inference, monitoring, retraining), after this update's
Windows/Docker checks pass.

## File inventory
The complete release includes all previous foundation files plus the additions
and updates listed below. Live .env, .venv, generated model stores, caches and
processed data are excluded. The original public source archive and static
verification evidence are included.

- `.dockerignore`
- `.env.example`
- `.github/workflows/ci.yml`
- `.github/workflows/train.yml`
- `.gitignore`
- `CONTRIBUTING.md`
- `Dockerfile`
- `LICENSE`
- `README.md`
- `SECURITY.md`
- `alembic.ini`
- `configs/.gitkeep`
- `configs/dataset.json`
- `configs/training.yaml`
- `data/README.md`
- `data/processed/.gitkeep`
- `data/raw/.gitkeep`
- `data/raw/uci-default.zip`
- `data/samples/.gitkeep`
- `docker-compose.yml`
- `docs/.gitkeep`
- `docs/architecture.md`
- `docs/batch-1-report.md`
- `docs/data_pipeline.md`
- `docs/milestone-1-report.md`
- `docs/model_card.md`
- `docs/registry.md`
- `docs/responsible_ai.md`
- `docs/verification/candidate.json`
- `docs/verification/comparison.json`
- `docs/verification/dataset.json`
- `docs/verification/http-verification.json`
- `docs/verification/installed-packages.txt`
- `docs/verification/pytest-output.txt`
- `docs/verification/reference-registry-audit.jsonl`
- `docs/verification/test-calibration.json`
- `docs/verification/test-evaluation.png`
- `docs/verification/validation-evaluation.png`
- `docs/verification/validation-shap_summary.json`
- `docs/verification/validation-shap_summary.png`
- `migrations/env.py`
- `migrations/script.py.mako`
- `migrations/versions/0001_foundation.py`
- `notebooks/.gitkeep`
- `pipelines/.gitkeep`
- `pyproject.toml`
- `reports/model/.gitkeep`
- `reports/monitoring/.gitkeep`
- `requirements-dev.lock`
- `requirements.lock`
- `scripts/.gitkeep`
- `scripts/upgrade_and_verify.py`
- `scripts/verify-batch.ps1`
- `scripts/verify_batch.py`
- `scripts/verify_compose.py`
- `src/ml_platform/__init__.py`
- `src/ml_platform/api/__init__.py`
- `src/ml_platform/api/main.py`
- `src/ml_platform/cli.py`
- `src/ml_platform/core/__init__.py`
- `src/ml_platform/core/config.py`
- `src/ml_platform/core/io.py`
- `src/ml_platform/core/training_config.py`
- `src/ml_platform/data/__init__.py`
- `src/ml_platform/data/ingestion.py`
- `src/ml_platform/data/splitting.py`
- `src/ml_platform/data/validation.py`
- `src/ml_platform/db/__init__.py`
- `src/ml_platform/db/models.py`
- `src/ml_platform/db/session.py`
- `src/ml_platform/features/__init__.py`
- `src/ml_platform/features/pipeline.py`
- `src/ml_platform/inference/__init__.py`
- `src/ml_platform/models/__init__.py`
- `src/ml_platform/models/gate.py`
- `src/ml_platform/models/registry.py`
- `src/ml_platform/monitoring/__init__.py`
- `src/ml_platform/observability/__init__.py`
- `src/ml_platform/observability/logging.py`
- `src/ml_platform/observability/telemetry.py`
- `src/ml_platform/retraining/__init__.py`
- `src/ml_platform/training/__init__.py`
- `src/ml_platform/training/evaluate.py`
- `src/ml_platform/training/explain.py`
- `src/ml_platform/training/train.py`
- `src/ml_platform/training/tuning.py`
- `tests/conftest.py`
- `tests/e2e/.gitkeep`
- `tests/e2e/test_training_registry.py`
- `tests/integration/.gitkeep`
- `tests/integration/test_postgres.py`
- `tests/tests_data.py`
- `tests/unit/.gitkeep`
- `tests/unit/test_api.py`
- `tests/unit/test_config.py`
- `tests/unit/test_data_pipeline.py`
- `tests/unit/test_model_gate.py`
