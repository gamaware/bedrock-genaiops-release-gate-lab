resource "aws_sns_topic" "alarms" {
  name              = "${var.name}-genai-release-alarms"
  kms_master_key_id = aws_kms_key.this.arn
}

# A jump in the share of guardrail interventions after a release means an
# attack in progress or a guardrail that now blocks normal questions. Either
# way the on-call engineer looks, and rolls back if the release caused it.
resource "aws_cloudwatch_metric_alarm" "guardrail_intervention_rate" {
  alarm_name          = "${var.name}-guardrail-intervention-rate"
  alarm_description   = "More than ${var.guardrail_intervention_alarm_pct}% of guardrail evaluations intervened for 15 minutes. Runbook: docs/runbook.md#guardrail-intervention-alarm"
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.guardrail_intervention_alarm_pct
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "rate"
    expression  = "IF(invocations > 0, 100 * intervened / invocations, 0)"
    label       = "Intervention rate (%)"
    return_data = true
  }

  metric_query {
    id = "intervened"
    metric {
      namespace   = "AWS/Bedrock/Guardrails"
      metric_name = "InvocationsIntervened"
      period      = 300
      stat        = "Sum"
      dimensions = {
        GuardrailArn     = aws_bedrock_guardrail.support.guardrail_arn
        GuardrailVersion = aws_bedrock_guardrail_version.support.version
      }
    }
  }

  metric_query {
    id = "invocations"
    metric {
      namespace   = "AWS/Bedrock/Guardrails"
      metric_name = "Invocations"
      period      = 300
      stat        = "Sum"
      dimensions = {
        GuardrailArn     = aws_bedrock_guardrail.support.guardrail_arn
        GuardrailVersion = aws_bedrock_guardrail_version.support.version
      }
    }
  }
}
