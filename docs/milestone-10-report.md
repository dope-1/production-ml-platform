# Milestone 10 deployment status

## Implemented and locally verifiable

- AWS reference architecture and Terraform for VPC, domainless CloudFront HTTPS, protected ALB,
  ECS/Fargate, private RDS,
  encrypted EFS, versioned private S3, ECR, Secrets Manager, IAM, CloudWatch and budget alerts.
- Two-phase deployment prevents ECS from starting before the image, model state and secrets exist.
- Digest-pinned release image containing only the verified registry controller and pinned RDS CA.
- Safe MLflow backup extraction with archive traversal/link rejection and a hashed release manifest.
- Production PostgreSQL `verify-full` support with an explicit RDS trust bundle.
- External HTTPS/auth/model/prediction verifier and infrastructure security contract tests.
- Documented operating, key rotation, cost, rollback, disaster recovery and teardown procedures.

## Intentionally pending

Milestone 10 is deployment-ready but is not represented as deployed until the owner supplies an AWS
account/region session, approves the Terraform plan, stages the protected release inputs and runs
the external verifier against the generated `*.cloudfront.net` URL. No purchased domain or ACM
certificate is required. These steps create billable resources and cannot be safely performed
against an unspecified account.

The completion evidence is a successful `reports/milestone-10-verification.json` from the real HTTPS
endpoint plus the applied Terraform state, ECR digest, S3 release manifest/version IDs and green CI
commit. Until then, Milestones 1-9 remain the last fully executed environment.
