# Milestone 10 deployment status

Status updated 23 September 2026: **implementation and earlier CI verified; AWS was partially
provisioned; CloudFront account verification declined; public deployment not verified**.
Region: Mumbai (`ap-south-1`). Milestone 10 remains incomplete.

## Implemented

- Domainless CloudFront HTTPS, protected ALB, ECS/Fargate, private RDS, encrypted EFS, private
  versioned S3, ECR, Secrets Manager, IAM, CloudWatch and optional budget alerts.
- Two-phase rollout, digest-pinned release image, validated backup extraction and RDS
  `verify-full` trust bundle.
- Production ingress controls, migrations, infrastructure contract tests and HTTPS verifier.
- Operations, rollback and teardown instructions in the [AWS guide](milestone-10-guide.md).

## Current execution evidence

The owner reported a successful [software/security CI run](https://github.com/dope-1/production-ml-platform/actions/runs/35446441466)
and staging at `.state/aws-release`. The first apply created resources including the ALB,
EFS mount targets and S3 lifecycle configuration, then failed on two independent blockers:

| Resource | Reported blocker | Required action |
|---|---|---|
| CloudFront | HTTP 403; AWS Support subsequently declined account verification | Current rollout blocked; a successful future review or reviewed architecture change is required |
| RDS | Free-plan restriction on requested seven-day backup retention | A one-day retention change was proposed; inspect the local `storage.tf` diff, validate, and confirm account acceptance before claiming it resolved |

These are owner-supplied execution results and the owner's AWS Support response. No successful
RDS creation, end-to-end cloud verification or completed cleanup has been reported. Preserve
Terraform state and keep `deploy_service = false` while the rollout is blocked. Repeating the
unchanged apply does not resolve the account restriction. Review the actual state and unused
resources for cleanup, since partially provisioned infrastructure can consume credits.
Any future deployment needs a fresh reviewed plan; do not reuse a saved plan from before a
partial apply or source changes. No paid-plan upgrade or domain purchase is part of this update.

## Remaining completion evidence

1. Successful resumed infrastructure apply, ECR image digest and S3 bootstrap upload.
2. Application secrets populated and phase-2 ECS deployment healthy.
3. `scripts/verify_aws_deployment.py` passes against the real CloudFront HTTPS endpoint.
4. Sanitized deployment evidence tied to the deployed commit, then updated status.
5. Reviewed cleanup and verification of remaining snapshots, backups, images and storage.

The completion report is `reports/milestone-10-verification.json`. Keep state, plans, keys,
backups and raw account/support screenshots private. Portfolio documentation can progress
while cloud screenshots and cloud benchmarks remain pending.
