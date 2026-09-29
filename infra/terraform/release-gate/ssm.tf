# Serving configuration per alias. The application reads its alias at start
# and on a short cache; the pipeline writes it (promote) and rewrites the
# previous value to roll back. Terraform creates the parameters only.
resource "aws_ssm_parameter" "release" {
  for_each = local.environments

  name        = "/${var.name}/${each.key}/release"
  description = "${var.name} ${each.key}: pinned model, prompt version, guardrail version and knowledge base"
  type        = "SecureString"
  key_id      = aws_kms_key.this.arn
  tier        = "Standard"
  value       = jsonencode({ release = "unset" })

  lifecycle {
    # Written by the release pipeline after the gate passes.
    ignore_changes = [value]
  }
}
