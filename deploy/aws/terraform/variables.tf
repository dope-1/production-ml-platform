variable "project_name" {
  description = "Short lowercase name used in AWS resource names."
  type        = string
  default     = "production-ml-platform"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.project_name))
    error_message = "project_name must be 3-32 lowercase letters, digits or hyphens."
  }
}

variable "environment" {
  type    = string
  default = "portfolio"
}

variable "aws_region" {
  description = "Deployment region; me-central-1 is the documented reference."
  type        = string
  default     = "me-central-1"
}

variable "domain_name" {
  description = "Public API hostname covered by certificate_arn."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9.-]+$", var.domain_name)) && !can(regex("[/:*]", var.domain_name))
    error_message = "domain_name must be a hostname without scheme, path, port or wildcard."
  }
}

variable "certificate_arn" {
  description = "Validated ACM certificate ARN in aws_region."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:acm:", var.certificate_arn))
    error_message = "certificate_arn must be an ACM certificate ARN."
  }
}

variable "route53_zone_id" {
  description = "Optional Route 53 hosted-zone ID. Leave null to create DNS externally."
  type        = string
  default     = null
  nullable    = true
}

variable "image_digest" {
  description = "Immutable sha256 digest of the release image pushed to this stack's ECR repository."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be sha256 followed by exactly 64 lowercase hex characters."
  }
}

variable "bootstrap_prefix" {
  description = "S3 key prefix containing extracted MLflow state for this release."
  type        = string
  default     = "releases/model-v1/mlflow"

  validation {
    condition     = !startswith(var.bootstrap_prefix, "/") && !endswith(var.bootstrap_prefix, "/")
    error_message = "bootstrap_prefix must not begin or end with a slash."
  }
}

variable "aws_cli_image" {
  description = "Reviewed AWS CLI image used by the one-shot bootstrap container."
  type        = string
  default     = "public.ecr.aws/aws-cli/aws-cli:2.31.22"
}

variable "allowed_cidrs" {
  description = "IPv4 CIDRs permitted to reach the HTTPS load balancer."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "deploy_service" {
  description = "Set true only after the ECR image, S3 bootstrap and two API secrets exist."
  type        = bool
  default     = false
}

variable "task_cpu" {
  type    = number
  default = 1024
}

variable "task_memory" {
  type    = number
  default = 3072
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_name" {
  type    = string
  default = "ml_platform"
}

variable "db_username" {
  type    = string
  default = "ml_platform_admin"
}

variable "db_final_snapshot_identifier" {
  description = "Unique final snapshot name used when the protected database is intentionally destroyed."
  type        = string
  default     = "production-ml-platform-portfolio-final"
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "budget_email" {
  description = "Optional email address for an 80% and 100% monthly budget alert."
  type        = string
  default     = null
  nullable    = true
}

variable "monthly_budget_usd" {
  type    = number
  default = 75
}
