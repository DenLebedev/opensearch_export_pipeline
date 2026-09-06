locals {
  monitored_lambda_functions = {
    initialize = aws_lambda_function.initialize.function_name
    worker     = aws_lambda_function.worker.function_name
    cleanup    = aws_lambda_function.cleanup.function_name
    finalize   = aws_lambda_function.finalize.function_name
  }

  alarm_actions = (
    var.alarm_sns_topic_arn == null
    ? []
    : [var.alarm_sns_topic_arn]
  )
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.monitored_lambda_functions

  alarm_name = (
    "${local.name_prefix}-${each.key}-lambda-errors"
  )

  alarm_description = (
    "The ${each.key} Lambda reported one or more errors."
  )

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = each.value
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "worker_throttles" {
  alarm_name = (
    "${local.name_prefix}-worker-lambda-throttles"
  )

  alarm_description = (
    "The export page worker Lambda is being throttled."
  )

  namespace   = "AWS/Lambda"
  metric_name = "Throttles"

  dimensions = {
    FunctionName = (
      aws_lambda_function.worker.function_name
    )
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "parent_execution_failed" {
  alarm_name = (
    "${local.name_prefix}-execution-failed"
  )

  alarm_description = (
    "The parent export State Machine failed."
  )

  namespace   = "AWS/States"
  metric_name = "ExecutionsFailed"

  dimensions = {
    StateMachineArn = (
      aws_sfn_state_machine.parent.arn
    )
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "parent_execution_timed_out" {
  alarm_name = (
    "${local.name_prefix}-execution-timed-out"
  )

  alarm_description = (
    "The parent export State Machine timed out."
  )

  namespace   = "AWS/States"
  metric_name = "ExecutionsTimedOut"

  dimensions = {
    StateMachineArn = (
      aws_sfn_state_machine.parent.arn
    )
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions
}