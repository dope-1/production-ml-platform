# Milestone 10: AWS deployment discontinued

Final status, 24 September 2026: cloud infrastructure code is retained as
reference, but no successful public AWS deployment is claimed. Cloud deployment
was discontinued by the owner; it is outside the completed local portfolio scope.

## Implementation and blockers

The implementation includes CloudFront, ALB, ECS/Fargate, RDS, EFS, ECR,
S3, Secrets Manager, IAM and CloudWatch, with Terraform and deployment checks.
Partial provisioning failed because CloudFront account verification was declined
and the requested RDS backup retention exceeded the account's free-plan limit.
The proposed one-day retention change was not verified and was not retained.

## Cleanup evidence

Owner-supplied execution output confirmed:

- Terraform completed with 0 added, 0 changed and 45 destroyed.
- S3 had no object versions or delete markers; ECR had no images.
- All five recovery points for the project's EFS file system were removed.
- The original automatic-backup vault policy was restored.
- The subsequent Terraform state listing was empty.

The two project secrets entered their configured seven-day deletion window;
permanent deletion has not yet been independently checked.
The automatic-backup vault is retained with its original protections.
These checks cover this project, not every resource in the AWS account.

Local Docker services, model artifacts and portfolio evidence remain available.
Terraform state and policy backups are kept privately and must not be committed.
Any future cloud deployment requires a new reviewed plan and live verification.
