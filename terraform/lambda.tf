locals {
  common_lambda_environment = {
    OPENSEARCH_ENDPOINT      = trimsuffix(var.opensearch_endpoint, "/")
    EXPORT_BUCKET            = aws_s3_bucket.exports.id
    EXPORT_TABLE             = aws_dynamodb_table.export_jobs.name
    PIT_KEEP_ALIVE           = var.pit_keep_alive
    DEFAULT_PAGE_SIZE        = tostring(var.default_page_size)
    DEFAULT_SLICE_COUNT      = tostring(var.default_slice_count)
    MAX_PAGES_PER_INVOCATION = tostring(var.max_pages_per_invocation)
    LAMBDA_SAFETY_MARGIN_MS  = tostring(var.lambda_safety_margin_ms)
    JOB_RETENTION_DAYS       = tostring(var.job_retention_days)
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.lambda_names

  name = "/aws/lambda/${each.value}"

  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "initialize" {
  function_name = local.lambda_names.initialize
  description   = "Initialize an OpenSearch export job."

  role    = aws_iam_role.lambda["initialize"].arn
  handler = "export_pipeline.initialize_export.handler.lambda_handler"
  runtime = var.lambda_runtime

  architectures = [
    var.lambda_architecture
  ]

  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

  memory_size = var.auxiliary_lambda_memory_size
  timeout     = var.auxiliary_lambda_timeout_seconds

  environment {
    variables = local.common_lambda_environment
  }

  vpc_config {
    subnet_ids = var.private_subnet_ids

    security_group_ids = [
      aws_security_group.lambda.id
    ]
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.initialize_lambda
  ]
}

resource "aws_lambda_function" "worker" {
  function_name = local.lambda_names.worker
  description   = "Export OpenSearch page groups to S3."

  role    = aws_iam_role.lambda["worker"].arn
  handler = "export_pipeline.export_page_group.handler.lambda_handler"
  runtime = var.lambda_runtime

  architectures = [
    var.lambda_architecture
  ]

  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

  memory_size = var.worker_memory_size
  timeout     = var.worker_timeout_seconds

  reserved_concurrent_executions = (
    var.worker_reserved_concurrency
  )

  environment {
    variables = local.common_lambda_environment
  }

  vpc_config {
    subnet_ids = var.private_subnet_ids

    security_group_ids = [
      aws_security_group.lambda.id
    ]
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.worker_lambda
  ]
}

resource "aws_lambda_function" "cleanup" {
  function_name = local.lambda_names.cleanup
  description   = "Close an export PIT and record failed exports."

  role    = aws_iam_role.lambda["cleanup"].arn
  handler = "export_pipeline.cleanup_export.handler.lambda_handler"
  runtime = var.lambda_runtime

  architectures = [
    var.lambda_architecture
  ]

  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

  memory_size = var.auxiliary_lambda_memory_size
  timeout     = var.auxiliary_lambda_timeout_seconds

  environment {
    variables = local.common_lambda_environment
  }

  vpc_config {
    subnet_ids = var.private_subnet_ids

    security_group_ids = [
      aws_security_group.lambda.id
    ]
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.cleanup_lambda
  ]
}

resource "aws_lambda_function" "finalize" {
  function_name = local.lambda_names.finalize
  description   = "Create the manifest for a completed export."

  role    = aws_iam_role.lambda["finalize"].arn
  handler = "export_pipeline.finalize_export.handler.lambda_handler"
  runtime = var.lambda_runtime

  architectures = [
    var.lambda_architecture
  ]

  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

  memory_size = var.auxiliary_lambda_memory_size
  timeout     = var.auxiliary_lambda_timeout_seconds

  environment {
    variables = local.common_lambda_environment
  }

  vpc_config {
    subnet_ids = var.private_subnet_ids

    security_group_ids = [
      aws_security_group.lambda.id
    ]
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.finalize_lambda
  ]
}