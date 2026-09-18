# Registry, promotion and rollback

Models are logged by MLflow's sklearn flavor before registration. A selected
finished run gets a checksummed evidence JSON and `controlled-training-v1` tag.
Registration checks run provenance, source identity, schema and every artifact's
SHA-256. Re-registering the same run is idempotent. A candidate alias alone never
means approved. The controller updates the production alias only after a gate.

The default gate checks validation ROC-AUC >= .65, average precision >= .30,
recall >= .60, Brier <= .23, single-row in-process P95 <= 100 ms, artifact size
<= 50 MB, grouped CV AP standard deviation <= .10, sex-group recall gap <= .20,
and finite/schema/reload checks. Both sex groups need adequate positive/negative
support. These are configurable engineering demo thresholds, not lending policy
or a fairness certification. Threshold selection targets validation recall .65.

Against an existing champion, the validation file digest must match. ROC-AUC,
AP and recall cannot regress by more than .01; Brier cannot worsen by more than
.01. AP must improve by at least .001. A different evaluation cohort is rejected:
re-evaluate both models on a governed common cohort in a future workflow. Test
metrics are reported but never used by the gate. Latency evidence is tied to the
recorded benchmark environment; rerun/benchmark on deployment hardware in Batch 2.

`promote` returns PROMOTE, REJECT, or UNCHANGED, with reasons. The software verifier
runs lint/types/tests before training and attempting promotion. Gate checks focus
on model evidence; the CLI alone is not a substitute for required software CI.

`rollback --version N --reason "..."` only accepts a previously approved version,
validates current integrity and absolute gates, and records the reason. It skips
the improvement requirement because rollback is an operational recovery action.
The current alias is retained if rollback validation fails.

## Audit and crash recovery

All lifecycle writers must share one persistent `.state/registry` directory.
FileLock serializes operations on this local host. JSONL events are flushed and
fsynced. A write-ahead pending.json precedes production alias changes. On a crash,
new mutations fail until `reconcile` checks whether the alias moved and writes
the recovery event. An unexpected externally changed alias requires manual
investigation. This avoids silently assuming a cross-system write was atomic.

The design is single-controller. It does not supply distributed fencing, a
cross-backend transaction, append-only remote audit enforcement or hostile-writer
tamper resistance. Never modify aliases/tags directly through MLflow UI in normal
operation. Registry write access is a trust boundary: writers can replace hashes
as well as artifacts. Hashes detect corruption, not malicious trusted admins.
Only controlled artifacts are deserialized; there is no model upload endpoint.

E2E tests execute real SQLite-backed MLflow registration, promotion, rejection,
artifact loading, tampering detection, rollback and pending-write recovery.
Synthetic fixtures and relaxed fixture-only thresholds are isolated from demo
runs. Actual UCI demo runs always use configs/training.yaml.

The loader also compares the active feature implementation digest to the trained
artifact, preventing silent reuse of a pickle with changed transformation code.

## Serving integration in Batch 2

`RegistryReader` performs verified reads without rewriting the controller's
identity file. The Docker API mounts the controller directory read-only and
uses its internal MLflow URI; the host CLI retains its original URI. Pending
controller operations block reloads. A serving snapshot already loaded before an
outage/pending operation remains available, with its original version reported.

Publish a model's monitoring reference from its original dataset before serving
it. `python -m ml_platform.ops reference` handles the current champion; the
retraining workflow publishes the candidate reference before gate application.
References do not modify the existing fitted-model artifact or its original hash
manifest. Each version's host dataset path is recorded in the controller directory
for the next retraining job. API reload is explicit after promotion/rollback.
