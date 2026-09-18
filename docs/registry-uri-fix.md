# Registry tracking-URI correction

The user's Windows run passed all 45 original tests, Docker/service health and
six-model UCI training, then failed downloading registry evidence. MLflow 2's
mlflow-artifacts resolver reads the process-global tracking URI even when the
MlflowClient was explicitly pointed at HTTP. Training ran in a child process;
the verifier's parent retained the default local file URI. Earlier verification
had trained and registered within a shared process, masking this boundary.

Fix: configure MLflow's global URI when constructing the single-backend Registry
controller, as well as configuring its client. Registration now resumes a version
created before evidence/alias finalization, without duplicating or demoting it.
The verifier adds --resume-registry to reuse reports/model/latest.json and the
existing dataset. No model weights, feature code or dependencies were changed.

Verification of the correction:
- Ruff lint/format and strict mypy passed.
- 46 tests passed; one PostgreSQL integration test skipped in this environment.
  The full suite is now 47 tests (two new regression tests).
- A fresh child Python process with no MLFLOW_TRACKING_URI successfully used the
  real HTTP artifact proxy, resumed a completed model, and loaded its approved
  artifact. Local result was UNCHANGED because it was already production.
- No retraining or Docker rebuild was needed for the resume check.

Apply the corrected archive over the same existing project; preserve .env,
.venv, .state, data/processed and reports/model. The archive does not contain
replacement live state. With Docker services still running:

```powershell
.\.venv\Scripts\python.exe scripts\verify_batch.py --resume-registry
```

Expect PROMOTE (or UNCHANGED if already approved), artifact_load_verified=true,
and production_version. A REJECT decision is still a valid gate outcome; retain
its reasons rather than bypassing checks. Resume intentionally does not rerun
software checks already completed in the user's failed verification session.
Reference model metrics elsewhere in this release are unchanged historical
training evidence; the registry controller source was subsequently patched.
