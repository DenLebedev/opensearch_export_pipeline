variable "aws_region" {
  description = "AWS region where export resources are deployed."
  type        = string
  default     = "eu-central-1"

  validation {
    condition     = length(trimspace(var.aws_region)) > 0
    error_message = "aws_region must not be empty."
  }
}

variable "project_name" {
  description = "Project name used to construct AWS resource names."
  type        = string
  default     = "opensearch-export"

  validation {
    condition = can(
      regex(
        "^[a-z][a-z0-9-]{2,30}$",
        var.project_name
      )
    )
    error_message = "project_name must contain lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"

  validation {
    condition = contains(
      [
        "dev",
        "test",
        "stage",
        "prod"
      ],
      var.environment
    )
    error_message = "environment must be dev, test, stage, or prod."
  }
}

variable "export_bucket_name" {
  description = "Optional explicit S3 bucket name. A generated name is used when null."
  type        = string
  default     = null

  validation {
    condition = (
      var.export_bucket_name == null
      || can(
        regex(
          "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
          var.export_bucket_name
        )
      )
    )
    error_message = "export_bucket_name must be a valid S3 bucket name."
  }
}

variable "enable_bucket_versioning" {
  description = "Enable versioning for export objects."
  type        = bool
  default     = false
}

variable "export_retention_days" {
  description = "Number of days exported data is retained in S3."
  type        = number
  default     = 30

  validation {
    condition     = var.export_retention_days >= 1
    error_message = "export_retention_days must be at least 1."
  }
}

variable "noncurrent_version_retention_days" {
  description = "Number of days noncurrent object versions are retained."
  type        = number
  default     = 7

  validation {
    condition     = var.noncurrent_version_retention_days >= 1
    error_message = "noncurrent_version_retention_days must be at least 1."
  }
}

variable "export_table_name" {
  description = "Optional explicit DynamoDB export jobs table name."
  type        = string
  default     = null
}

variable "enable_dynamodb_point_in_time_recovery" {
  description = "Enable DynamoDB point-in-time recovery."
  type        = bool
  default     = true
}

variable "job_retention_days" {
  description = "Default job metadata retention period."
  type        = number
  default     = 90

  validation {
    condition     = var.job_retention_days >= 1
    error_message = "job_retention_days must be at least 1."
  }
}

variable "additional_tags" {
  description = "Additional tags applied to all supported AWS resources."
  type        = map(string)
  default     = {}
}

variable "opensearch_endpoint" {
  description = "HTTPS endpoint of the existing OpenSearch domain."
  type        = string

  validation {
    condition = can(
      regex(
        "^https://",
        var.opensearch_endpoint
      )
    )
    error_message = "opensearch_endpoint must start with https://."
  }
}

variable "opensearch_domain_arn" {
  description = "ARN of the existing OpenSearch domain."
  type        = string

  validation {
    condition = can(
      regex(
        "^arn:[^:]+:es:[^:]+:[0-9]{12}:domain/.+$",
        var.opensearch_domain_arn
      )
    )
    error_message = "opensearch_domain_arn must be a valid OpenSearch domain ARN."
  }
}

variable "python_command" {
  description = "Local Python command used to build the Lambda bundle."
  type        = string
  default     = "python"
}

variable "lambda_runtime" {
  description = "Python runtime used by AWS Lambda."
  type        = string
  default     = "python3.13"
}

variable "lambda_architecture" {
  description = "Instruction set architecture used by Lambda."
  type        = string
  default     = "arm64"

  validation {
    condition = contains(
      [
        "arm64",
        "x86_64"
      ],
      var.lambda_architecture
    )
    error_message = "lambda_architecture must be arm64 or x86_64."
  }
}

variable "worker_memory_size" {
  description = "Memory allocated to the page export Lambda."
  type        = number
  default     = 1024

  validation {
    condition = (
      var.worker_memory_size >= 128
      && var.worker_memory_size <= 10240
    )
    error_message = "worker_memory_size must be between 128 and 10240 MB."
  }
}

variable "worker_timeout_seconds" {
  description = "Timeout of the page export Lambda."
  type        = number
  default     = 900

  validation {
    condition = (
      var.worker_timeout_seconds >= 30
      && var.worker_timeout_seconds <= 900
    )
    error_message = "worker_timeout_seconds must be between 30 and 900."
  }
}

variable "worker_reserved_concurrency" {
  description = "Reserved concurrency that protects OpenSearch from excessive load."
  type        = number
  default     = 4

  validation {
    condition     = var.worker_reserved_concurrency >= 1
    error_message = "worker_reserved_concurrency must be at least 1."
  }
}

variable "auxiliary_lambda_memory_size" {
  description = "Memory allocated to initialization, cleanup, and finalization Lambdas."
  type        = number
  default     = 256
}

variable "auxiliary_lambda_timeout_seconds" {
  description = "Timeout of initialization, cleanup, and finalization Lambdas."
  type        = number
  default     = 60

  validation {
    condition = (
      var.auxiliary_lambda_timeout_seconds >= 10
      && var.auxiliary_lambda_timeout_seconds <= 900
    )
    error_message = "auxiliary_lambda_timeout_seconds must be between 10 and 900."
  }
}

variable "pit_keep_alive" {
  description = "OpenSearch PIT keep-alive interval."
  type        = string
  default     = "10m"
}

variable "default_page_size" {
  description = "Default number of documents requested per OpenSearch page."
  type        = number
  default     = 1000

  validation {
    condition = (
      var.default_page_size >= 1
      && var.default_page_size <= 10000
    )
    error_message = "default_page_size must be between 1 and 10000."
  }
}

variable "default_slice_count" {
  description = "Default number of parallel OpenSearch slices."
  type        = number
  default     = 16

  validation {
    condition     = var.default_slice_count >= 1
    error_message = "default_slice_count must be at least 1."
  }
}

variable "max_pages_per_invocation" {
  description = "Maximum pages processed by one worker invocation."
  type        = number
  default     = 5

  validation {
    condition     = var.max_pages_per_invocation >= 1
    error_message = "max_pages_per_invocation must be at least 1."
  }
}

variable "lambda_safety_margin_ms" {
  description = "Worker safety margin before the Lambda timeout."
  type        = number
  default     = 30000

  validation {
    condition     = var.lambda_safety_margin_ms >= 1000
    error_message = "lambda_safety_margin_ms must be at least 1000."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention period."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [
        1,
        3,
        5,
        7,
        14,
        30,
        60,
        90,
        120,
        150,
        180,
        365,
        400,
        545,
        731,
        1096,
        1827,
        2192,
        2557,
        2922,
        3288,
        3653
      ],
      var.log_retention_days
    )
    error_message = "log_retention_days must be supported by CloudWatch Logs."
  }
}

variable "vpc_id" {
  description = "ID of the existing VPC containing OpenSearch."
  type        = string

  validation {
    condition = can(
      regex("^vpc-[a-zA-Z0-9]+$", var.vpc_id)
    )
    error_message = "vpc_id must be a valid VPC ID."
  }
}

variable "private_subnet_ids" {
  description = "Private subnet IDs used by Lambda functions."
  type        = list(string)

  validation {
    condition = (
      length(var.private_subnet_ids) >= 2
      && alltrue([
        for subnet_id in var.private_subnet_ids :
        can(regex("^subnet-[a-zA-Z0-9]+$", subnet_id))
      ])
    )
    error_message = "Provide at least two valid private subnet IDs."
  }
}

variable "opensearch_security_group_id" {
  description = "Security Group attached to the existing OpenSearch domain."
  type        = string

  validation {
    condition = can(
      regex(
        "^sg-[a-zA-Z0-9]+$",
        var.opensearch_security_group_id
      )
    )
    error_message = "opensearch_security_group_id must be a valid Security Group ID."
  }
}

variable "manage_opensearch_ingress_rule" {
  description = "Allow Terraform to add Lambda HTTPS access to the OpenSearch Security Group."
  type        = bool
  default     = true
}

variable "create_s3_vpc_endpoint" {
  description = "Create an S3 Gateway VPC endpoint."
  type        = bool
  default     = true
}

variable "create_dynamodb_vpc_endpoint" {
  description = "Create a DynamoDB Gateway VPC endpoint."
  type        = bool
  default     = true
}

variable "private_route_table_ids" {
  description = "Route table IDs associated with the private Lambda subnets."
  type        = list(string)

  validation {
    condition = alltrue([
      for route_table_id in var.private_route_table_ids :
      can(regex("^rtb-[a-zA-Z0-9]+$", route_table_id))
    ])
    error_message = "private_route_table_ids must contain valid route table IDs."
  }
}

variable "max_concurrency" {
  description = "Maximum number of OpenSearch slices processed concurrently."
  type        = number
  default     = 4

  validation {
    condition     = var.max_concurrency >= 1
    error_message = "max_concurrency must be at least 1."
  }
}

variable "step_functions_log_level" {
  description = "CloudWatch logging level for Step Functions."
  type        = string
  default     = "ERROR"

  validation {
    condition = contains(
      [
        "ALL",
        "ERROR",
        "FATAL"
      ],
      var.step_functions_log_level
    )
    error_message = "step_functions_log_level must be ALL, ERROR, or FATAL."
  }
}

variable "alarm_sns_topic_arn" {
  description = "Optional SNS topic ARN receiving CloudWatch alarm notifications."
  type        = string
  default     = null
}