variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project identifier used as prefix for all resource names"
  type        = string
  default     = "pgx-latam"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
  }
}

variable "lake_bucket_name" {
  description = "Name of the S3 data lake bucket (must be globally unique)"
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup name"
  type        = string
  default     = "pgx-latam-workgroup"
}

variable "athena_output_prefix" {
  description = "S3 prefix within lake_bucket for Athena query results"
  type        = string
  default     = "athena-results"
}

variable "athena_data_scanned_limit_gb" {
  description = "Per-query data scanned limit in GB for the Athena workgroup"
  type        = number
  default     = 100
}

variable "glue_catalog_database_prefix" {
  description = "Prefix for Glue catalog database names (bronze_pgx, silver_pgx, gold_pgx)"
  type        = string
  default     = "pgx_latam"
}

variable "pipeline_failure_email" {
  description = "Email address for SNS pipeline failure notifications"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository for OIDC trust (format: owner/repo)"
  type        = string
  default     = "enriqew/pgx-latam-atlas"
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    Project   = "pgx-latam-atlas"
    ManagedBy = "terraform"
  }
}
