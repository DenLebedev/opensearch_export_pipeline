resource "aws_dynamodb_table" "export_jobs" {
  name = local.export_table_name

  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "requestId"

  attribute {
    name = "requestId"
    type = "S"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = (
      var.enable_dynamodb_point_in_time_recovery
    )
  }

  server_side_encryption {
    enabled = true
  }
}