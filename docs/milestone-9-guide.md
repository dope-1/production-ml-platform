# Milestone 9 — CI/CD and security

This patch updates the verified Milestone 8 checkout to version **0.4.0**. It
contains only changed/new files. Model artifacts, runtime dependency pins,
feature transformation source, PostgreSQL schema and saved monitoring data are
unchanged. No retraining or model promotion is part of the upgrade.

## Windows / VS Code upgrade

1. Start Docker Desktop.
2. Copy the contents of the ZIP's `production-ml-platform` directory into
   `E:\Projects\production-ml-platform`, allowing replacement of the included files.
   Merge the folders; keep `.env`, `.venv`, `.state`, data and Docker volumes.
3. From VS Code's PowerShell terminal at the project root, run:

```powershell
.\.venv\Scripts\python.exe scripts\upgrade_milestone9.py
```

The script enables auth, generates a missing API key, preserves existing strong
keys and DB credentials, updates the editable package, runs lint/format/type/source
security checks and focused tests, and rebuilds **only `ml-api`**. It starts existing
PostgreSQL/MLflow services if necessary, then verifies API authorization, request
limits, container controls and one prediction in the `verification` cohort. It
does not rerun training, migrations, simulations or the 200-request benchmark.
The first build after changing the Dockerfile may refresh its dependency layer;
later source-only changes keep that layer cached.

Do not use `--init-ci` locally; it creates a fresh disposable configuration and
refuses to overwrite `.env`. `--configure-only` just initializes authentication
and is useful before a fresh install's original bootstrap scripts.

The output is `reports/milestone-9-verification.json`. On failure, fix the reported
check and rerun the same command; it preserves credentials on repeated runs.
Do not use `docker compose down --volumes` on your project.

## Dashboard and API keys

Open [the dashboard](http://127.0.0.1:8000/api/v1/dashboard), open `.env` in VS Code,
and copy only the **value** of `ML_API_KEY` into the dashboard's API key field.
Click **Connect** and select **verification**, **benchmark** or a synthetic cohort.
Use **7 days** if yesterday's observations fall outside the default 24-hour window.
Refreshing the browser requires re-entering the key. Clear key removes it and the
visible report from that tab. Never paste keys into chat, screenshots or Git.

At [API documentation](http://127.0.0.1:8000/docs), choose **Authorize** and enter
the API key; use the separate admin key only when an admin operation is needed.

| Header / role | Allowed operations |
|---|---|
| No key | Local health/readiness, dashboard shell, development docs |
| `X-API-Key` | Predictions/explanations in `live`, model metadata, monitoring/history, metrics |
| `X-Admin-Key` | All of the above, labels, reload, snapshots, non-live scoring cohorts |

For a local PowerShell prediction without echoing the key:

```powershell
$headers = @{ 'X-API-Key' = (.\.venv\Scripts\python.exe -c "from ml_platform.core.config import Settings; print(Settings().api_key.get_secret_value())") }
$body = Get-Content examples\predict.json -Raw
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/predict -Headers $headers -ContentType application/json -Body $body
Remove-Variable headers
```

401 means missing/incorrect credentials, 403 means the operation requires admin,
413 means body too large, 415 means unsupported body format, and 429 includes a
`Retry-After` header. The quota is shared by all clients using the same key. CLI
batch/monitor/training commands continue to use local DB/registry access directly.

## CI and model validation

Push this patch with the rest of your existing project to its GitHub repository.
No repository or cloud deployment is created by this patch.

- **Software and security CI** runs on push, pull request, manual dispatch and a
  weekly schedule. Linux runs lint, formatting, typing, dependency consistency,
  full tests with real PostgreSQL and an 80% coverage floor. Windows runs unit
  tests and dependency consistency checks. Both platforms audit pinned packages.
- **Security** checks application source with Ruff `S` rules and dependencies with
  pip-audit. **Compose** scans the clean checkout for secrets, builds/starts the
  services, verifies actual HTTP/container controls, tests rate-limit rejection,
  and scans the API image for HIGH/CRITICAL vulnerabilities, including unfixed ones.
- **ci-required** fails if any required job fails, is skipped or is cancelled.
  Set this as a required check in your repository's branch protection/ruleset.
  Branch protection cannot be enabled by simply adding workflow YAML.
- **Model validation** is a separate manual workflow in the Actions tab. Run it
  after model, preprocessing or training dependency changes. It performs controlled
  UCI training, evaluation, artifact integrity/schema tests, promotion gating,
  host/container parity and an HTTP latency benchmark in disposable services.
  Its registry's `production` alias belongs only to CI; it never changes your local
  champion or deploys a cloud model.

Reports are retained as Actions artifacts for seven days. Secrets, `.env`, model
volumes and private input data are not uploaded. The workflows prepare and validate
the deliverable; external deployment belongs to Milestone 10.

To run source/dependency scans locally in an isolated environment:

```powershell
.\.venv\Scripts\python.exe -m venv .security-venv
.\.security-venv\Scripts\python.exe -m pip install -r requirements-security.txt
.\.security-venv\Scripts\python.exe scripts\security_scan.py
```

Reports go to `reports/security/`. Scanner tools are version-pinned separately;
their own transitive dependencies are resolved by pip. Runtime/training locks are
not silently upgraded. A vulnerability or unavailable advisory service blocks the
gate. Review fixes, regenerate affected locks and rerun compatibility/model checks;
do not add blanket ignores or automatically upgrade the serving ML stack.
The Trivy image/secret scans run in the Compose CI job. These commands need network
access and the real scan results; configuration alone is not a passed scan.

## Scope and next step

Local upgrade verification does not execute GitHub Actions or claim a clean live
vulnerability database. The shipped verification report records what was actually
run during implementation. After the local upgrade and both GitHub workflows are
green, the next milestone is **10 — cloud deployment**, including managed secrets,
private MLflow/database networking, HTTPS, costs and rollback.

The API currently uses shared service keys and a single-worker in-memory limiter.
Public deployment needs an ingress/authentication design and a shared limiter for
multiple instances. See [Security](../SECURITY.md) for the complete boundary.

Implementation references: [pip-audit](https://github.com/pypa/pip-audit),
[Ruff security rules](https://docs.astral.sh/ruff/rules/#flake8-bandit-s),
[Trivy exit-code behavior](https://trivy.dev/docs/latest/configuration/others/),
[GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use).
