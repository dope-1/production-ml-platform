# CI and dependency security update — 18 September 2026

This patch includes the earlier Windows isolation fix. Apply only this combined patch.
It is a tested dependency/compatibility update, not a claim that the Docker image has
zero vulnerabilities. The rebuilt image must still pass the strict Trivy gate.

## What changed

- Windows CI creates a virtual environment before dependency installation, excluding
  the runner's preinstalled pipx and its conflicting packaging requirement.
- MLflow, MLflow Skinny, and MLflow Tracing are pinned to 3.16.1; PyArrow to 23.0.1.
  Cryptography remains at the original 50.0.1. Both universal lockfiles were regenerated
  together; the remaining changes are dependencies required by MLflow 3.
- Training explicitly saves cloudpickle models and uploads them as run artifacts,
  preserving the registry's existing run/model layout. Hash verification and controlled
  promotion still occur before model deserialization. Existing feature-pipeline bytes,
  scikit-learn, NumPy, pandas, LightGBM, and SHAP versions are unchanged.
- Registry checks explicitly reject missing model source/run IDs under MLflow 3's types.
  The tampering test now modifies the real artifact store instead of a downloaded copy.
- MLflow's server host/origin allowlists explicitly allow the local UI and Compose hostname.
- MLflow telemetry is disabled by default in the application, CI, Docker, and upgrade script.
- The Docker base explicitly stays on Python 3.12 / Debian trixie. Build steps apply
  available Debian package upgrades, and CI pulls the current base before building.
- Push-triggered CI is limited to main; pull requests still run CI. This prevents the
  duplicate push-plus-PR runs seen on Dependabot branches. Dependabot's Docker updates
  keep Python 3.12; interpreter migrations need separate compatibility work.
- Dependency scan failures now print package/advisory details in the job log.

## Apply and run GitHub CI first

1. Extract the ZIP contents directly into `E:\Projects\production-ml-platform` and
   replace the included files. The ZIP's root contains files such as Dockerfile and
   pyproject.toml; do not create another nested project folder.
2. In the VS Code PowerShell terminal, run:

```powershell
cd E:\Projects\production-ml-platform
git diff --stat
git add -- .github Dockerfile docker-compose.yml pyproject.toml requirements.lock requirements-dev.lock RELEASE-SHA256.json src scripts tests docs
git diff --cached --stat
git commit -m "Fix CI isolation and update MLflow security dependencies"
git push origin main
```

This push starts Software and security CI. No local database migration happens merely
by extracting or pushing the patch. Leave existing Dependabot PRs unmerged while
checking the main branch. Historical red runs will remain in the Actions history.

## Update the local running project

The new MLflow server requires a database migration. Do not simply rebuild and start
it against the old SQLite database. With Docker Desktop running, finish any local
training/retraining/registry commands, then run:

```powershell
.\.venv\Scripts\python.exe scripts\upgrade_security.py
```

The script first verifies the existing service and records its serving model version.
It installs the updated development lock, checks installed dependencies, runs lint,
format, typing, and tests, and builds the images. It then stops the API and MLflow,
copies the registry control directory, backs up the entire stopped MLflow volume,
checks the backup, migrates SQLite, restarts MLflow/API, and verifies that the model
version has not changed. It does not retrain, promote a new model, delete volumes,
change the database password, or replace API keys.

Backups are under `.state/backups/security-<timestamp>/`. Keep these private. They
include the original MLflow image ID, named-volume identity, registry control state,
database, and artifacts. If an upgrade step fails, stop there and retain the backup
and error. Do not use `docker compose down --volumes` or attempt to downgrade the
migrated SQLite schema in place. Restoring the old deployment requires restoring its
backup and original image together, while services are stopped.

## Verified here

- 100 tests passed, 1 PostgreSQL integration test skipped; coverage 82.44%.
- Ruff lint/format/source-security checks and mypy (43 source files) passed.
- Installed dependency compatibility check passed.
- Live pip-audit of both final lockfiles: zero known vulnerabilities, no ignored IDs.
- Real MLflow 2 SQLite model/registry migrated to MLflow 3.16.1: same approved version
  and prediction within 1e-12. No feature-pipeline hash change.
- Real MLflow 3 HTTP server: proxied artifact upload/download passed; internal service
  host accepted and an unrelated host rejected.
- Backup validator tested with complete, missing-database, empty-database, and truncated
  archives. Workflow/Compose YAML and package checksum manifest checked.

Docker and Windows are unavailable in the patch-building environment. The full Docker
backup/restart script, Windows job, and rebuilt-image scan require your machine or CI.
The PostgreSQL integration test remains enabled in the GitHub Linux checks job.

## Remaining container limitation

The supplied image report includes Debian findings with no fixed stable package listed.
For example, Debian currently lists CVE-2026-78408 as vulnerable in both bookworm and
trixie. Switching to bookworm alone would not fix it. Pulling the base and applying apt
upgrades addresses available fixes; it cannot guarantee removal of upstream-unfixed
findings. The existing HIGH/CRITICAL gate, including unfixed findings, remains enabled.
No vulnerability exclusions, ignore-unfixed setting, or continue-on-error was added.

If Compose alone fails at Container vulnerability scan, download the NEW run's
container-security-evidence artifact. That identifies what remains after this rebuild;
review it before deployment. A green dependency audit is not a green container audit.

References:
- https://mlflow.org/docs/latest/ml/mlflow-3/
- https://mlflow.org/docs/latest/self-hosting/migration/
- https://security-tracker.debian.org/tracker/CVE-2026-78408
