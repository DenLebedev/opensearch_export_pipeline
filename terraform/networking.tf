data "aws_vpc" "selected" {
  id = var.vpc_id
}

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${var.aws_region}.s3"
}

data "aws_prefix_list" "dynamodb" {
  name = "com.amazonaws.${var.aws_region}.dynamodb"
}

check "gateway_endpoint_route_tables" {
  assert {
    condition = (
      (
        !var.create_s3_vpc_endpoint
        && !var.create_dynamodb_vpc_endpoint
      )
      || length(var.private_route_table_ids) > 0
    )

    error_message = "private_route_table_ids must be provided when creating Gateway VPC endpoints."
  }
}

resource "aws_security_group" "lambda" {
  name        = "${local.name_prefix}-lambda"
  description = "Network access for OpenSearch export Lambda functions."
  vpc_id      = var.vpc_id

  tags = {
    Name = "${local.name_prefix}-lambda"
  }
}

resource "aws_vpc_security_group_egress_rule" "opensearch" {
  security_group_id = aws_security_group.lambda.id

  description                  = "HTTPS access from Lambda to OpenSearch."
  referenced_security_group_id = var.opensearch_security_group_id

  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
}

resource "aws_vpc_security_group_egress_rule" "s3" {
  security_group_id = aws_security_group.lambda.id

  description    = "HTTPS access from Lambda to S3."
  prefix_list_id = data.aws_prefix_list.s3.id

  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
}

resource "aws_vpc_security_group_egress_rule" "dynamodb" {
  security_group_id = aws_security_group.lambda.id

  description    = "HTTPS access from Lambda to DynamoDB."
  prefix_list_id = data.aws_prefix_list.dynamodb.id

  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
}

resource "aws_vpc_security_group_egress_rule" "dns_udp" {
  security_group_id = aws_security_group.lambda.id

  description = "UDP DNS resolution inside the VPC."
  cidr_ipv4   = data.aws_vpc.selected.cidr_block

  ip_protocol = "udp"
  from_port   = 53
  to_port     = 53
}

resource "aws_vpc_security_group_egress_rule" "dns_tcp" {
  security_group_id = aws_security_group.lambda.id

  description = "TCP DNS resolution inside the VPC."
  cidr_ipv4   = data.aws_vpc.selected.cidr_block

  ip_protocol = "tcp"
  from_port   = 53
  to_port     = 53
}

resource "aws_vpc_security_group_ingress_rule" "opensearch_from_lambda" {
  count = var.manage_opensearch_ingress_rule ? 1 : 0

  security_group_id = var.opensearch_security_group_id

  description                  = "HTTPS access from export Lambdas."
  referenced_security_group_id = aws_security_group.lambda.id

  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
}

resource "aws_vpc_endpoint" "s3" {
  count = var.create_s3_vpc_endpoint ? 1 : 0

  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = var.private_route_table_ids

  tags = {
    Name = "${local.name_prefix}-s3"
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  count = var.create_dynamodb_vpc_endpoint ? 1 : 0

  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"

  route_table_ids = var.private_route_table_ids

  tags = {
    Name = "${local.name_prefix}-dynamodb"
  }
}