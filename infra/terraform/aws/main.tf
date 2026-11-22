terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "sololedger"
      Environment = var.environment
      ManagedBy   = "terraform"
      Portfolio   = "apple-ads-prep"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "environment" {
  type    = string
  default = "demo"
}

resource "aws_s3_bucket" "private_uploads" {
  bucket_prefix = "sololedger-uploads-${var.environment}-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "private_uploads" {
  bucket                  = aws_s3_bucket.private_uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads_ttl" {
  bucket = aws_s3_bucket.private_uploads.id
  rule {
    id     = "expire-temporary-csv-uploads"
    status = "Enabled"
    expiration {
      days = 7
    }
  }
}

resource "aws_s3_bucket" "frontend_spa" {
  bucket_prefix = "sololedger-web-${var.environment}-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend_spa" {
  bucket                  = aws_s3_bucket.frontend_spa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_ecr_repository" "backend" {
  name                 = "sololedger-${var.environment}-backend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecs_cluster" "main" {
  name = "sololedger-${var.environment}-cluster"
}

resource "aws_cloudwatch_log_group" "services" {
  name              = "/ecs/sololedger-${var.environment}"
  retention_in_days = 7
}

resource "aws_secretsmanager_secret" "django_secret" {
  name_prefix             = "sololedger-${var.environment}-secret-"
  recovery_window_in_days = 0
}

