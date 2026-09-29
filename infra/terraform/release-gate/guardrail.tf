locals {
  blocked_message = "Sorry, I can't help with that request. I can help with Harbor Goods orders, shipping, returns and products."

  content_filters = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"]

  denied_topics = {
    investment-advice = {
      definition = "Recommendations about stocks, funds, cryptocurrency or other investments."
      examples   = ["Which stocks should I buy with my refund?", "Is bitcoin a good investment?"]
    }
    medical-advice = {
      definition = "Diagnosis or treatment of a health condition, symptom or injury."
      examples   = ["Is this rash serious?", "What medicine should I take for a headache?"]
    }
    competitor-pricing = {
      definition = "Comparing Harbor Goods prices with named or unnamed competitors, or quoting competitor prices."
      examples   = ["Is Harbor Goods cheaper than other home stores?", "What does the store across town charge?"]
    }
  }

  pii_actions = {
    PHONE                    = "ANONYMIZE"
    EMAIL                    = "ANONYMIZE"
    ADDRESS                  = "ANONYMIZE"
    CREDIT_DEBIT_CARD_NUMBER = "BLOCK"
  }

  loyalty_id_pattern = "HG-LOY-[0-9]{4}"

  # Any change here publishes a new guardrail version (see aws_bedrock_guardrail_version).
  guardrail_fingerprint = substr(sha256(jsonencode({
    content  = local.content_filters
    topics   = local.denied_topics
    pii      = local.pii_actions
    regex    = local.loyalty_id_pattern
    message  = local.blocked_message
    grounded = [0.75, 0.5]
  })), 0, 12)
}

resource "aws_bedrock_guardrail" "support" {
  name                      = "${var.name}-support"
  description               = "Harbor Goods support assistant: content, denied topics, PII and grounding."
  blocked_input_messaging   = local.blocked_message
  blocked_outputs_messaging = local.blocked_message
  kms_key_arn               = aws_kms_key.this.arn

  content_policy_config {
    dynamic "filters_config" {
      for_each = local.content_filters
      content {
        type            = filters_config.value
        input_strength  = "HIGH"
        output_strength = "HIGH"
      }
    }

    # Prompt attacks are only evaluated on input.
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  topic_policy_config {
    dynamic "topics_config" {
      for_each = local.denied_topics
      content {
        name       = topics_config.key
        type       = "DENY"
        definition = topics_config.value.definition
        examples   = topics_config.value.examples
      }
    }
  }

  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = local.pii_actions
      content {
        type   = pii_entities_config.key
        action = pii_entities_config.value
      }
    }

    regexes_config {
      name        = "loyalty-id"
      description = "Harbor Goods loyalty member IDs"
      pattern     = local.loyalty_id_pattern
      action      = "ANONYMIZE"
    }
  }

  contextual_grounding_policy_config {
    filters_config {
      type      = "GROUNDING"
      threshold = 0.75
    }
    filters_config {
      type      = "RELEVANCE"
      threshold = 0.5
    }
  }
}

# Releases pin a numbered, immutable version, never DRAFT.
resource "aws_bedrock_guardrail_version" "support" {
  guardrail_arn = aws_bedrock_guardrail.support.guardrail_arn
  description   = "config ${local.guardrail_fingerprint}"
  skip_destroy  = var.retain_guardrail_versions
}
