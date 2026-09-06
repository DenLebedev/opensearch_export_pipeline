data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  parent_state_machine_arn = join(
    ":",
    [
      "arn",
      data.aws_partition.current.partition,
      "states",
      var.aws_region,
      data.aws_caller_identity.current.account_id,
      "stateMachine",
      local.parent_state_machine_name
    ]
  )

  parent_execution_arn = join(
    ":",
    [
      "arn",
      data.aws_partition.current.partition,
      "states",
      var.aws_region,
      data.aws_caller_identity.current.account_id,
      "execution",
      local.parent_state_machine_name,
      "*"
    ]
  )

  slice_execution_arn = join(
    ":",
    [
      "arn",
      data.aws_partition.current.partition,
      "states",
      var.aws_region,
      data.aws_caller_identity.current.account_id,
      "execution",
      local.slice_state_machine_name,
      "*"
    ]
  )

  step_functions_event_rule_arn = join(
    ":",
    [
      "arn",
      data.aws_partition.current.partition,
      "events",
      var.aws_region,
      data.aws_caller_identity.current.account_id,
      "rule/StepFunctionsGetEventsForStepFunctionsExecutionRule"
    ]
  )
}

data "aws_iam_policy_document" "step_functions_assume_role" {
  statement {
    sid     = "AllowStepFunctionsService"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type = "Service"

      identifiers = [
        "states.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role" "slice_state_machine" {
  name = "${local.slice_state_machine_name}-role"

  assume_role_policy = data.aws_iam_policy_document.step_functions_assume_role.json
}

resource "aws_iam_role" "parent_state_machine" {
  name = "${local.parent_state_machine_name}-role"

  assume_role_policy = data.aws_iam_policy_document.step_functions_assume_role.json
}

data "aws_iam_policy_document" "slice_state_machine" {
  statement {
    sid = "InvokePageWorker"

    actions = [
      "lambda:InvokeFunction"
    ]

    resources = [
      aws_lambda_function.worker.arn
    ]
  }
}

resource "aws_iam_role_policy" "slice_state_machine" {
  name = "${local.slice_state_machine_name}-policy"
  role = aws_iam_role.slice_state_machine.id

  policy = data.aws_iam_policy_document.slice_state_machine.json
}

data "aws_iam_policy_document" "parent_state_machine" {
  statement {
    sid = "InvokeExportLambdas"

    actions = [
      "lambda:InvokeFunction"
    ]

    resources = [
      aws_lambda_function.initialize.arn,
      aws_lambda_function.cleanup.arn,
      aws_lambda_function.finalize.arn
    ]
  }

  statement {
    sid = "StartDistributedMapExecutions"

    actions = [
      "states:StartExecution"
    ]

    resources = [
      local.parent_state_machine_arn,
      aws_sfn_state_machine.slice.arn
    ]
  }

  statement {
    sid = "ManageSynchronousExecutions"

    actions = [
      "states:DescribeExecution",
      "states:StopExecution"
    ]

    resources = [
      local.parent_execution_arn,
      local.slice_execution_arn
    ]
  }

  statement {
    sid = "ManageStepFunctionsEventRule"

    actions = [
      "events:PutTargets",
      "events:PutRule",
      "events:DescribeRule"
    ]

    resources = [
      local.step_functions_event_rule_arn
    ]
  }
}

resource "aws_iam_role_policy" "parent_state_machine" {
  name = "${local.parent_state_machine_name}-policy"
  role = aws_iam_role.parent_state_machine.id

  policy = data.aws_iam_policy_document.parent_state_machine.json
}

data "aws_iam_policy_document" "step_functions_logging" {
  statement {
    sid = "DeliverStepFunctionsLogs"

    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups"
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "slice_state_machine_logging" {
  name = "${local.slice_state_machine_name}-logging"
  role = aws_iam_role.slice_state_machine.id

  policy = data.aws_iam_policy_document.step_functions_logging.json
}

resource "aws_iam_role_policy" "parent_state_machine_logging" {
  name = "${local.parent_state_machine_name}-logging"
  role = aws_iam_role.parent_state_machine.id

  policy = data.aws_iam_policy_document.step_functions_logging.json
}