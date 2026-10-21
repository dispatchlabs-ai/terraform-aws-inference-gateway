variable "name" {
  description = "Short unique prefix for this dedicated gateway deployment."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,23}$", var.name))
    error_message = "Use 2–24 lowercase letters, digits or hyphens, beginning with a letter."
  }
}
variable "vpc_id" { type = string }
variable "subnet_ids" {
  description = "At least two public subnets in distinct availability zones, with Internet Gateway routes."
  type        = list(string)
  validation {
    condition     = length(distinct(var.subnet_ids)) >= 2
    error_message = "Provide at least two distinct public subnets."
  }
}
variable "domain_name" { type = string }
variable "zone_id" { type = string }
variable "manage_dns" {
  description = "Create the public A alias; disable when the caller owns an existing record."
  type        = bool
  default     = true
}
variable "image" {
  description = "ECR image pinned by sha256 digest, containing Dispatch's ECS-aware inference gateway."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9/_-]+@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Use a private ECR image URI pinned by sha256 digest."
  }
}
variable "image_repository_arn" { type = string }
variable "configuration_uri" {
  description = "s3://bucket/key of immutable, non-secret gateway configuration."
  type        = string
  validation {
    condition     = can(regex("^s3://[^/]+/.+", var.configuration_uri))
    error_message = "Provide an S3 object URI."
  }
}
variable "configuration_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.configuration_sha256))
    error_message = "Provide the configuration SHA-256 as lowercase hexadecimal."
  }
}
variable "session_secret_arn" { type = string }
variable "connection_secret_arns" {
  description = "Existing Secrets Manager credentials. This module never receives secret values."
  type        = list(string)
  validation {
    condition     = length(var.connection_secret_arns) > 0
    error_message = "Provide at least one credential secret ARN."
  }
}
variable "kms_key_arns" {
  description = "Optional customer-managed keys for reading configuration/credentials and writing credentials."
  type        = list(string)
  default     = []
}
variable "desired_count" {
  description = "Two ingress tasks by default. Zero stages infrastructure or fences every provider writer."
  type        = number
  default     = 2
  validation {
    condition     = var.desired_count >= 0 && floor(var.desired_count) == var.desired_count
    error_message = "Use a nonnegative integer."
  }
}
variable "cpu" {
  type    = number
  default = 512
}
variable "memory" {
  type    = number
  default = 2048
}
variable "cpu_architecture" {
  type    = string
  default = "X86_64"
  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "Use X86_64 or ARM64 with a compatible image."
  }
}
variable "log_retention_days" {
  type    = number
  default = 30
}
variable "alarm_actions" {
  description = "Optional SNS topic ARNs. Empty creates alarms without external notification delivery."
  type        = list(string)
  default     = []
}
variable "tags" {
  type    = map(string)
  default = {}
}
