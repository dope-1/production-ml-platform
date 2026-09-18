# Security

This is a local engineering demonstration, not an approved lending service.
Report vulnerabilities privately to the repository owner; do not disclose keys or
customer data in public issues.

## API controls

Milestone 9 enables authentication in Compose and `.env.example`. Use a distinct
random `ML_API_KEY` for predictions, explanations and monitoring; use
`ML_ADMIN_KEY` for labels, model reload, monitoring snapshots and non-live traffic.
Admin credentials also authorize ordinary API calls. Keys require 32–256 printable
ASCII characters without whitespace; comparison uses constant-time comparison.
Keep both keys private. Shared keys provide service roles, not individual users,
tenants, revocation lists or an identity provider.

`/health`, `/ready`, the dashboard shell and development documentation remain
public on the local interface. Monitoring data and `/metrics` require a key.
Production disables documentation and requires authentication and verified TLS
for PostgreSQL. Configure its CA using libpq/`PGSSLROOTCERT`. An explicitly allowed
Host is required. CORS uses explicit origins, with HTTPS origins in production.

Ingress limits JSON bodies to 1 MiB, bounds body reception to ten seconds, rejects
compressed/ambiguous bodies, and runs authorization before model/database work.
Each shared key has a 600-request/minute quota; anonymous socket IPs have 60/minute.
All application routes except health/readiness probes consume a quota. Invalid
credentials consume the anonymous quota. The limiter stores at most 2,048 identities,
denies new identities when full, and expires entries after one minute. Uvicorn
uses one worker, bounds concurrent connections/tasks to 64, and ignores forwarded
IP headers. These are process-local fixed windows, reset on restart; multiple
instances require a shared gateway/limiter before deployment. Probes need ingress
restrictions in a public deployment.

Responses use `no-store`, `nosniff`, framing restrictions and a Content Security
Policy. Dashboard scripts/styles use exact SHA-256 CSP hashes; key entry stays in
tab memory, with no URL, cookie or browser-storage persistence. Development
Swagger UI uses its own inline script hash and the explicit jsDelivr CDN.
Logs exclude request payloads, credentials and exception messages. Rejections
before routing appear under the bounded `security` Prometheus label; they are not
added to the prediction ledger.

## Secrets and filesystem

Local credentials belong in the ignored `.env`; the upgrade preserves existing
strong keys and DB credentials. For managed deployments use `ML_DB_PASSWORD_FILE`,
`ML_API_KEY_FILE`, `ML_ADMIN_KEY_FILE` with read-only mounted secret files. Do not
set both a value and its file setting. The settings loader reads at most 4 KiB,
fails on unreadable/conflicting secrets, and masks validation inputs. Secret
files, key files and local environments are excluded from Git and Docker context.
Compose is still a local environment-file setup: `_FILE` support does not provision
a cloud secret manager or automatically mount host files.

There is no HTTP batch/model upload endpoint. Batch CSV scoring is a trusted local
CLI operation: exact numeric schema, unique positive IDs, 64 MiB input and 100,000
row defaults, bounded chunks, no symlink destinations, exclusive temporary file,
and atomic output replacement. A failed validation rolls back all DB rows and
leaves the previous output intact. Use trusted local directories; the database
commit and final file rename are not a distributed transaction.

## Model and container boundary

Only controlled training/registry artifacts can load. Identity, version/status,
run lineage, approval, feature-code compatibility and exact model/reference
checksums are checked before deserialization. A reload failure retains the last
verified snapshot. Do not upload arbitrary pickle/joblib models for execution.
Hashes detect corruption, not a malicious trusted registry writer who can alter
both artifacts and hashes. Model artifacts remain executable trusted content.

Compose publishes API, PostgreSQL and MLflow only on loopback. The API is non-root,
has a read-only root filesystem and registry mount, drops all Linux capabilities,
and enables `no-new-privileges`. MLflow has no authentication in this local setup;
never expose it publicly. Registry controllers share one local control directory.
Cloud isolation, managed identity/secrets, TLS termination and deployment rollback
are Milestone 10.

## Required security gates

CI runs Ruff's full `S` rule set over application source, `pip-audit --strict` over
pinned development/runtime dependencies on Linux and Windows, a Trivy secret scan
of the clean checkout, and a Trivy HIGH/CRITICAL scan of the built API image,
including unfixed findings. Audit failures/unavailable advisory services fail the
job; there are no vulnerability ignore lists or `continue-on-error` bypasses.
Two line-specific S603 annotations cover a resolved Git executable with constant
arguments and no shell/input interpolation; they are not vulnerability exceptions.

Use the `ci-required` branch-protection check and require review of workflow and
security changes. Actions use full commit pins, read-only tokens, no persisted Git
credentials and disposable local services. The manual model workflow validates
only an isolated CI registry and has no production deployment permissions.
Weekly CI and Dependabot help surface newly disclosed findings; dependency upgrades
still require review, regenerated locks and model compatibility validation.

Passing scans means no findings under those checks at that time, not proof that
all code or model artifacts are safe. Do not call a release security-verified until
the actual GitHub scan jobs pass. See [Milestone 9 guide](docs/milestone-9-guide.md).
