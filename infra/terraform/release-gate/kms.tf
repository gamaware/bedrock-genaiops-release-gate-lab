# One customer managed key for the prompt, the guardrail, the SSM release
# parameters, the evaluation bucket and the alarm topic.
resource "aws_kms_key" "this" {
  description             = "${var.name}: GenAI release configuration and evaluation evidence"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchAlarmsPublishToTheTopic"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
      },
    ]
  })
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.name}-genai-release"
  target_key_id = aws_kms_key.this.key_id
}
