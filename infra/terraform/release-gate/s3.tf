# Evaluation datasets and results: golden and red-team sets uploaded by the
# live gate, Amazon Bedrock evaluation job output, and release evidence.
resource "aws_s3_bucket" "evaluations" {
  #checkov:skip=CKV_AWS_18:Server access logs are not kept for this bucket; CloudTrail data events are the audit source when a client needs one.
  #checkov:skip=CKV_AWS_144:Evaluation evidence is reproducible from the repository; cross-Region replication is not worth the cost.
  #checkov:skip=CKV2_AWS_62:No consumer reacts to new objects; the pipeline reads results directly.
  bucket_prefix = "${var.name}-evals-"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_ownership_controls" "evaluations" {
  bucket = aws_s3_bucket.evaluations.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "evaluations" {
  bucket                  = aws_s3_bucket.evaluations.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "evaluations" {
  bucket = aws_s3_bucket.evaluations.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evaluations" {
  bucket = aws_s3_bucket.evaluations.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.this.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "evaluations" {
  bucket = aws_s3_bucket.evaluations.id

  rule {
    id     = "expire-evaluation-data"
    status = "Enabled"

    filter {}

    expiration {
      days = var.evaluation_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "evaluations" {
  bucket = aws_s3_bucket.evaluations.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.evaluations.arn, "${aws_s3_bucket.evaluations.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.evaluations]
}
