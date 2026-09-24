# Responsible use

This is an engineering portfolio demonstration using historical public Taiwan
credit-card data. It is not validated for lending, eligibility, pricing, fraud
accusations, or current UAE customers. Geographic, temporal and selection bias
limit transfer. The task is next-month default classification, not transaction
fraud or causal risk assessment.

Sex, age, education and marriage are retained for auditing but excluded from
model inputs, together with ID and outcome. Their exclusion does not eliminate
proxies or bias. Reports include sex and age-group sample sizes, recall, false-
positive/negative rates and Brier scores when support is sufficient. Small groups
are explicitly marked insufficient; no protected characteristics are inferred.
The sex recall-gap guardrail is one diagnostic, not proof the model is fair.

False positives can unjustly burden reliable customers; false negatives can
underestimate financial risk. Threshold choice is an explicit recall/precision
trade-off based on validation evidence. No real lending cost matrix or regulatory
policy is claimed. Calibration curves and Brier scores evaluate probabilities;
no post-hoc calibration is applied in this batch. SHAP contributions explain
associations under the fitted model, not causal effects or individual certainty.

Any real use needs representative prospective data, legally reviewed governance,
appropriate human review/appeal, privacy controls and ongoing performance checks.
Milestones 6–8 implement drift and delayed-label monitoring plus gated retraining.
Synthetic cohorts demonstrate detection and are isolated from live triggers; they
do not establish real production performance. A separately supplied dataset with
new features and observed labels is required for retraining. Public source records
must not be confused with private customer data suitable for unrestricted logging.

## Assessment and residual risks

| Risk | Implemented evidence/control | Remaining limitation |
|---|---|---|
| Transfer | Historical Taiwan provenance disclosed | No prospective UAE or current-customer validation |
| Disparate impact | Demographics excluded from inputs; support-aware subgroup diagnostics | Proxies remain; a small recall gap does not establish fairness |
| False positives | Validation threshold and held-out confusion matrix published | Test precision 0.4611; no actual lending cost model supplied |
| Explanations | SHAP output space and reconstruction checked | Association is not causation or individual certainty |
| Biased outcomes | Coverage and per-class label-support gates | Observed labels may differ systematically from missing labels |
| Model change | Artifact checks, promotion/comparison policy, audit and explicit reload | Single controller; repeated holdout use needs independent oversight |
| Telemetry | Coarse bins; raw inputs excluded from ledger | Scores/bins remain potentially sensitive; retention is an operator action |
| Deployment | Scans, reviewed exception policy, API/admin roles | Temporary HIGH findings; CloudFront verification declined; AWS deployment unverified |

The reference validation sex-group recall gap is approximately 0.0011: one point estimate,
not a statistical guarantee or certification. Review its support counts in
[candidate.json](verification/candidate.json). No demographic attribute is inferred at inference.

Any real decision use requires representative consented data, independent evaluation, human
review/appeal, security/privacy review and an approved operating policy. This portfolio does
not make consequential lending decisions.
