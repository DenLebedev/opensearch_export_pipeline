data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    sid     = "AllowLambdaService"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each = local.lambda_names

  name = "${each.value}-role"

  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  for_each = aws_iam_role.lambda

  role = each.value.name

  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  for_each = aws_iam_role.lambda

  role = each.value.name

  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "initialize_lambda" {
  statement {
    sid = "ManageExportJob"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem"
    ]

    resources = [
      aws_dynamodb_table.export_jobs.arn
    ]
  }

  statement {
    sid = "ManageOpenSearchPIT"

    actions = [
      "es:ESHttpPost",
      "es:ESHttpDelete"
    ]

    resources = [
      "${var.opensearch_domain_arn}/*"
    ]
  }
}

resource "aws_iam_role_policy" "initialize_lambda" {
  name = "${local.name_prefix}-initialize-policy"
  role = aws_iam_role.lambda["initialize"].id

  policy = data.aws_iam_policy_document.initialize_lambda.json
}

data "aws_iam_policy_document" "worker_lambda" {
  statement {
    sid = "SearchOpenSearch"

    actions = [
      "es:ESHttpGet",
      "es:ESHttpPost"
    ]

    resources = [
      "${var.opensearch_domain_arn}/*"
    ]
  }

  statement {
    sid = "WriteExportObjects"

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.exports.arn}/exports/*"
    ]
  }
}

resource "aws_iam_role_policy" "worker_lambda" {
  name = "${local.name_prefix}-worker-policy"
  role = aws_iam_role.lambda["worker"].id

  policy = data.aws_iam_policy_document.worker_lambda.json
}

data "aws_iam_policy_document" "cleanup_lambda" {
  statement {
    sid = "UpdateExportJob"

    actions = [
      "dynamodb:UpdateItem"
    ]

    resources = [
      aws_dynamodb_table.export_jobs.arn
    ]
  }

  statement {
    sid = "CloseOpenSearchPIT"

    actions = [
      "es:ESHttpDelete"
    ]

    resources = [
      "${var.opensearch_domain_arn}/*"
    ]
  }
}

resource "aws_iam_role_policy" "cleanup_lambda" {
  name = "${local.name_prefix}-cleanup-policy"
  role = aws_iam_role.lambda["cleanup"].id

  policy = data.aws_iam_policy_document.cleanup_lambda.json
}

data "aws_iam_policy_document" "finalize_lambda" {
  statement {
    sid = "CompleteExportJob"

    actions = [
      "dynamodb:UpdateItem"
    ]

    resources = [
      aws_dynamodb_table.export_jobs.arn
    ]
  }

  statement {
    sid = "WriteExportManifest"

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.exports.arn}/exports/*"
    ]
  }
}

resource "aws_iam_role_policy" "finalize_lambda" {
  name = "${local.name_prefix}-finalize-policy"
  role = aws_iam_role.lambda["finalize"].id

  policy = data.aws_iam_policy_document.finalize_lambda.json
}