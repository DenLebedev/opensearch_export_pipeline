check "worker_concurrency" {
  assert {
    condition = (
      var.max_concurrency
      <= var.worker_reserved_concurrency
    )

    error_message = "max_concurrency must not exceed worker_reserved_concurrency."
  }
}

resource "aws_cloudwatch_log_group" "state_machine" {
  for_each = local.state_machine_names

  name = (
    "/aws/vendedlogs/states/${each.value}"
  )

  retention_in_days = var.log_retention_days
}

resource "aws_sfn_state_machine" "slice" {
  name     = local.slice_state_machine_name
  role_arn = aws_iam_role.slice_state_machine.arn
  type     = "STANDARD"

  definition = templatefile(
    "${path.module}/../statemachines/slice.asl.json.tftpl",
    {
      export_page_group_lambda_arn = (
        aws_lambda_function.worker.arn
      )
    }
  )

  logging_configuration {
    include_execution_data = false
    level                  = var.step_functions_log_level

    log_destination = (
      "${aws_cloudwatch_log_group.state_machine["slice"].arn}:*"
    )
  }

  depends_on = [
    aws_iam_role_policy.slice_state_machine,
    aws_iam_role_policy.slice_state_machine_logging
  ]
}

resource "aws_sfn_state_machine" "parent" {
  name     = local.parent_state_machine_name
  role_arn = aws_iam_role.parent_state_machine.arn
  type     = "STANDARD"

  definition = templatefile(
    "${path.module}/../statemachines/parent.asl.json.tftpl",
    {
      initialize_export_lambda_arn = (
        aws_lambda_function.initialize.arn
      )

      export_page_group_lambda_arn = (
        aws_lambda_function.worker.arn
      )

      cleanup_export_lambda_arn = (
        aws_lambda_function.cleanup.arn
      )

      finalize_export_lambda_arn = (
        aws_lambda_function.finalize.arn
      )

      slice_state_machine_arn = (
        aws_sfn_state_machine.slice.arn
      )

      max_concurrency = var.max_concurrency
    }
  )

  logging_configuration {
    include_execution_data = false
    level                  = var.step_functions_log_level

    log_destination = (
      "${aws_cloudwatch_log_group.state_machine["parent"].arn}:*"
    )
  }

  depends_on = [
    aws_iam_role_policy.parent_state_machine,
    aws_iam_role_policy.parent_state_machine_logging
  ]
}