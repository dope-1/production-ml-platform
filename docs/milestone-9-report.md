# Milestone 9 verification report

Version: **0.4.0**. Implementation verified on Linux with Python 3.12.14 on
18 September 2026. This report distinguishes executed checks from configured CI.

## Executed locally

| Check | Result |
|---|---|
| Full pytest suite | **96 passed, 1 skipped**, 31 upstream warnings; 44.17 seconds |
| Coverage | **82.47%**, above the new 80% CI gate |
| Focused upgrade/API/security suite | **56 passed** |
| Final security/script regression checks | **22 passed** |
| Ruff lint and formatting | Passed |
| Ruff source security rules (`--select S`) | Passed |
| Strict mypy | Passed, 43 application source files |
| Installed dependency consistency | Passed, 111 installed packages checked with `uv pip check` |
| Workflow YAML | Parsed; direct action commit pins, permissions, timeouts and no bypass flags checked |
| Dashboard JavaScript | Syntax checked; key submission/clearing and stale response discard exercised with a mocked DOM/fetch |
| Compatibility | Feature transformation bytes and both runtime/development lock files unchanged |

The full suite includes real isolated training/registration/promotion/loading,
tampered-artifact rejection before deserialization, approval/reconciliation,
rollback, monitoring references and rejected challenger retention. API tests use
FastAPI's real ASGI stack; inference/storage fixtures use SQLite and trained test
models. They do not substitute for deployment verification against PostgreSQL.

New security tests cover anonymous denial before parsing/model work, API/admin
roles, encoded/trailing route variants, duplicate credential headers, size limits
with declared and streamed bodies, malformed framing, body timeout/disconnect,
content types/encoding, Host/CORS controls, quotas/expiry/bounded limiter memory,
forwarded-IP spoofing, CSP hashes, secret-file configuration, credential masking,
repeatable key upgrades, batch row/byte-limit rollback, scan failure propagation
and container-hardening rejection. API ingress security code reached 98% coverage
in the full run.

The feature source SHA-256 remains:
`4005a3f88dc86dd4865e28129eaf02d6e0845dcdb983fa7e097d213548535be2`.
No trained model, registry alias, user database or dependency version was changed.

## Requires your environment or GitHub Actions

The PostgreSQL integration test was skipped because this environment has no
running PostgreSQL service (`TEST_DATABASE=1` was not set). Docker is unavailable
here. The actual rebuilt image, read-only container settings and HTTP security
checks must therefore run on your PC using `scripts/upgrade_milestone9.py`; it
writes `reports/milestone-9-verification.json` and checks the deployed version.

GitHub Actions, pip-audit's live advisory lookup, Trivy's secret scan and the image
vulnerability scan were **not executed here**. Their fail-closed workflows are
included. No claim of a clean vulnerability scan or green remote CI is made.
The Windows CI job and the manual Docker model-validation workflow also require
execution in GitHub Actions. Dashboard checks here use ASGI and JavaScript logic,
not a rendered-browser visual test.

Your earlier successful Milestone 8 run remains the evidence for PostgreSQL,
Docker/MLflow, 120 prediction parity checks, delayed labels and the 200-request
benchmark. Milestone 9's upgrade preserves that model and data, adds one tagged
verification prediction, and runs only the checks needed for this change.

Next: apply the patch, run the upgrade command in the
[guide](milestone-9-guide.md), then run the GitHub CI and Model validation workflows.
Cloud deployment remains Milestone 10.
