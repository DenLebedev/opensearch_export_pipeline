resource "aws_s3_bucket" "exports" {
  bucket = var.export_bucket_name

  bucket_prefix = (
    var.export_bucket_name == null
    ? "${local.name_prefix}-"
    : null
  )

  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "exports" {
  bucket = aws_s3_bucket.exports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "exports" {
  bucket = aws_s3_bucket.exports.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }

    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_versioning" "exports" {
  bucket = aws_s3_bucket.exports.id

  versioning_configuration {
    status = (
      var.enable_bucket_versioning
      ? "Enabled"
      : "Suspended"
    )
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  depends_on = [
    aws_s3_bucket_versioning.exports
  ]

  rule {
    id     = "expire-export-data"
    status = "Enabled"

    filter {
      prefix = "exports/"
    }

    expiration {
      days = var.export_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = (
        var.noncurrent_version_retention_days
      )
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "export_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type = "*"

      identifiers = [
        "*"
      ]
    }

    actions = [
      "s3:*"
    ]

    resources = [
      aws_s3_bucket.exports.arn,
      "${aws_s3_bucket.exports.arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"

      values = [
        "false"
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "exports" {
  bucket = aws_s3_bucket.exports.id
  policy = data.aws_iam_policy_document.export_bucket.json

  depends_on = [
    aws_s3_bucket_public_access_block.exports
  ]
}