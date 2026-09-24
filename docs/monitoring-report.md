# Monitoring report

## Reviewed local capture: 22 September 2026

The [monitoring capture](verification/portfolio/monitoring.md) and
[JSON evidence](verification/portfolio/evidence.json) record model version `1`, run
`3ed34af186ec4fe28dcbd36f5136a5f6`, in approximately 06:27 UTC-to-06:27 UTC windows over
21–22 September 2026. Each cohort has its precise window recorded in the JSON.

| Cohort | Predictions | Drift status | Observed labels |
|---|---:|---|---:|
| live | 0 | insufficient_samples | 0 |
| verification | 0 | insufficient_samples | 0 |
| benchmark | 210 | drift | 0 |

The benchmark total matches 200 timed requests plus 10 warmups. Repeated public example
inputs can produce a distribution unlike the training reference; the drift alert is not proof
of model degradation. All three cohorts correctly report `insufficient_labels` for quality
assessment. No labels or live-traffic results have been invented.

The benchmark cohort's server-recorded P95 was 188.58 ms across 210 events. The client
benchmark P95 was 227.17 ms across 200 timed requests. Their timing boundaries and inclusion
of warmups differ; they should not be presented as the same latency measure.
To view these observations after the 24-hour window expires, choose the dashboard's
`benchmark` cohort and `7 days` window while the capture remains within that window.

## Measured reference behavior

[Reference HTTP verification](verification/batch-2-http.json) records 120 prediction-parity
checks, 120 attached historical labels and four seeded 600-row simulation scenarios. The
reference observation store was SQLite. These are historical/demo observations, not current
customer outcomes or measurements of the owner's PostgreSQL stack.

| Scenario | Decision | Score PSI | Mean score |
|---|---|---:|---:|
| No shift | Stable | 0.0147 | 0.2153 |
| Mild | Stable | 0.0172 | 0.2227 |
| Moderate | Drift | 0.6672 | 0.3745 |
| Severe | Drift | 4.6623 | 0.5979 |

Mild remaining stable is the observed result. Simulation perturbs inputs without inventing
outcomes; it demonstrates detection, not concept drift or degraded real-world performance.

## Implemented policy

| Signal | Evidence required / rule |
|---|---|
| Feature drift | >=100 predictions; numeric PSI >=0.20 or categorical total variation >=0.15 |
| Overall input drift | >=3 changed features, or the prediction-drift rule |
| Prediction drift | Score PSI >=0.20 and absolute mean-score shift >=0.03 or positive-rate shift >=0.10; PSI required in both cases |
| Label performance | >=100 labels, >=10 per class, >=50% coverage |
| Degradation | ROC-AUC/AP drop >0.05, recall drop >0.10, or Brier increase >0.05 against validation |
| Calibration | Brier, fixed-bin calibration and ECE when label support passes |
| Operations | Requests/errors, latency percentiles, missing inputs, Prometheus counters/histograms |

Source: `src/ml_platform/monitoring/report.py`. These thresholds are investigation heuristics.
Validation and current populations may differ; a metric delta is not a causal effect estimate.

## Evidence sufficiency and response

- Empty windows return `insufficient_samples` or `insufficient_labels`, not a positive verdict
  on quality. Outcomes can be delayed or selectively observed.
- Prediction windows use model/cohort/time isolation. HTTP events use cohort/time and may span
  versions during rollout. Early security rejections are recorded separately in Prometheus.
- Each window is capped at 50,000 predictions/events; shorten it if exceeded. Windows support
  1–720 hours. No silent sampling is performed.
- Verification, benchmark and synthetic cohorts cannot trigger live retraining. Real new
  features and observed outcomes must arrive as a separately validated dataset.

Use the [demo guide](demo-guide.md) to capture current local monitoring to
`reports/portfolio/monitoring.md` and `evidence.json`. Their 24-hour windows can include earlier
traffic; they are not identical to the benchmark timing interval.

Investigate version/cohort/window first, then changed features and input-pipeline changes.
Examine sufficiently supported labels before concluding degradation. Train a challenger only
with validated new data; retain the promotion/comparison policy and explicitly reload serving
after approval. Preserve the journal when investigating rollback. No cloud monitoring success
or live response SLA is claimed.
