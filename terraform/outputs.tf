output "export_bucket_name" {
  description = "S3 bucket that stores exported datasets."
  value       = aws_s3_bucket.exports.id
}

output "export_bucket_arn" {
  description = "ARN of the export S3 bucket."
  value       = aws_s3_bucket.exports.arn
}

output "export_jobs_table_name" {
  description = "DynamoDB table that stores export job state."
  value       = aws_dynamodb_table.export_jobs.name
}

output "export_jobs_table_arn" {
  description = "ARN of the export jobs DynamoDB table."
  value       = aws_dynamodb_table.export_jobs.arn
}

output "initialize_lambda_arn" {
  description = "ARN of the export initialization Lambda."
  value       = aws_lambda_function.initialize.arn
}

output "worker_lambda_arn" {
  description = "ARN of the page export Lambda."
  value       = aws_lambda_function.worker.arn
}

output "cleanup_lambda_arn" {
  description = "ARN of the export cleanup Lambda."
  value       = aws_lambda_function.cleanup.arn
}

output "finalize_lambda_arn" {
  description = "ARN of the export finalization Lambda."
  value       = aws_lambda_function.finalize.arn
}

output "lambda_bundle_path" {
  description = "Local path of the generated Lambda deployment ZIP."
  value       = data.archive_file.lambda_bundle.output_path
}

output "lambda_security_group_id" {
  description = "Security Group used by export Lambda functions."
  value       = aws_security_group.lambda.id
}

output "s3_vpc_endpoint_id" {
  description = "ID of the S3 Gateway VPC endpoint, when created."

  value = try(
    aws_vpc_endpoint.s3[0].id,
    null
  )
}

output "dynamodb_vpc_endpoint_id" {
  description = "ID of the DynamoDB Gateway VPC endpoint, when created."

  value = try(
    aws_vpc_endpoint.dynamodb[0].id,
    null
  )
}

output "slice_state_machine_arn" {
  description = "ARN of the slice processing State Machine."
  value       = aws_sfn_state_machine.slice.arn
}

output "parent_state_machine_arn" {
  description = "ARN of the parent export State Machine."
  value       = aws_sfn_state_machine.parent.arn
}

output "parent_state_machine_name" {
  description = "Name of the parent export State Machine."
  value       = aws_sfn_state_machine.parent.name
}

output "step_functions_log_groups" {
  description = "CloudWatch Log Groups used by Step Functions."

  value = {
    for key, log_group in aws_cloudwatch_log_group.state_machine :
    key => log_group.name
  }
}