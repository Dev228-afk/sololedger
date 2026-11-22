# CLOUD_APPROVAL.md — SoloLedger

- **Deployment Status**: `BLOCKED_EXTERNAL` (AWS CLI absent, no IAM credentials configured, and no user spend authorization granted).
- **Target Region**: `us-west-2`
- **Services**: Private S3 statement upload bucket (`block_public_* = true`, 7-day auto-expiry lifecycle), Private S3 frontend bucket behind CloudFront, ECR (`sololedger-demo-backend`), ECS Fargate (Django API + Celery worker tasks), optional RDS `db.t4g.micro` (Postgres 16) + ElastiCache Redis `cache.t4g.micro`, CloudWatch Logs (7-day retention), Secrets Manager (`recovery_window_in_days = 0`).
- **Estimated Cost**: ~$0.06/hour active (< $0.50 for a 2-hour verification window).
- **Maximum Test Duration**: 2 hours followed immediately by `terraform destroy -auto-approve`.
- **Privacy & Secret Policy**: Never upload real customer statements or use public object ACLs/URLs. `SOLOLEDGER_LLM_PROVIDER=mock` remains enabled unless external LLM spend is separately approved.
- **Teardown Command**: `cd infra/terraform/aws && terraform destroy -auto-approve`
- **Required Action to Unblock**: Install `aws` & `terraform`, export valid IAM least-privilege credentials, and grant explicit budget sign-off.

