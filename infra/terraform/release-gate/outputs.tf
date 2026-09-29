output "gate_role_arn" {
  description = "Set as the AWS_GATE_ROLE_ARN variable of the genai-staging GitHub environment."
  value       = aws_iam_role.gate.arn
}

output "promote_role_arn" {
  description = "Set as the AWS_PROMOTE_ROLE_ARN variable of the genai-prod GitHub environment."
  value       = aws_iam_role.promote.arn
}

output "evaluator_role_arn" {
  description = "Service role to pass to Amazon Bedrock evaluation jobs."
  value       = aws_iam_role.evaluator.arn
}

output "evaluation_bucket" {
  description = "Bucket for evaluation datasets, job results and release evidence."
  value       = aws_s3_bucket.evaluations.bucket
}

output "guardrail_id" {
  description = "Guardrail ID to pin in release.yaml."
  value       = aws_bedrock_guardrail.support.guardrail_id
}

output "guardrail_version" {
  description = "Latest published guardrail version, to pin in release.yaml."
  value       = aws_bedrock_guardrail_version.support.version
}

output "prompt_arn" {
  description = "Managed prompt ARN to pin in release.yaml (with a version the live gate publishes)."
  value       = aws_bedrockagent_prompt.support_answer.arn
}

output "release_parameters" {
  description = "SSM parameter per alias (staging, prod) holding the serving configuration."
  value       = { for alias, parameter in aws_ssm_parameter.release : alias => parameter.name }
}

output "alarm_topic_arn" {
  description = "SNS topic for the guardrail alarm; subscribe the on-call channel."
  value       = aws_sns_topic.alarms.arn
}
