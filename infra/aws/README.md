# SoloLedger AWS Infrastructure Notes

Defines the Terraform resources in `../../infra/terraform/aws/main.tf` (private S3 statement upload bucket with 7-day lifecycle expiry, private S3 frontend SPA bucket, ECR backend image repository for API + Celery workers, ECS cluster, 7-day CloudWatch Logs, and Secrets Manager).

Live deployment is **`BLOCKED_EXTERNAL`** pending explicit spend authorization in `../../CLOUD_APPROVAL.md` and valid AWS CLI/Terraform credentials.

