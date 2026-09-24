# Current local monitoring

Captured: 2026-09-22T06:27:41.128133+00:00

Model version: 1; MLflow run: `3ed34af186ec4fe28dcbd36f5136a5f6`.

Window: 24 hours per cohort; earlier traffic in the window can be included.

| Cohort | Predictions | Drift | Labels | Coverage | Performance |
|---|---:|---|---:|---:|---|
| live | 0 | insufficient_samples | 0 | 0.0% | insufficient_labels |
| verification | 0 | insufficient_samples | 0 | 0.0% | insufficient_labels |
| benchmark | 210 | drift | 0 | 0.0% | insufficient_labels |

Insufficient evidence is not proof of model quality. Repeated benchmark inputs can cause drift and do not represent a real population. No labels were created by this collector. Review source timestamps in evidence.json; monitoring windows differ from the benchmark timing interval. No AWS monitoring result is claimed.
