# Offline: the mocked provider never calls AWS and needs no credentials.
# Account 111122223333 is the AWS documentation example ID. Runs use
# command = apply so computed ARNs exist (the mock generates them) and the
# policy documents can be decoded and asserted.
mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "111122223333" }
  }
  override_data {
    target = data.aws_partition.current
    values = { partition = "aws" }
  }
  override_data {
    target = data.aws_region.current
    values = { region = "us-east-1" }
  }
  mock_resource "aws_bedrock_guardrail" {
    defaults = {
      guardrail_arn = "arn:aws:bedrock:us-east-1:111122223333:guardrail/hg7k2m9q4x1a"
      guardrail_id  = "hg7k2m9q4x1a"
    }
  }
  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-east-1:111122223333:harbor-support-genai-release-alarms"
    }
  }
  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:111122223333:key/0b7c3a1e-2f4d-4c6b-9a8e-5d1f2e3c4b5a"
    }
  }
}

variables {
  github_repository        = "harbor-goods/support-assistant"
  github_oidc_provider_arn = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
}

run "guardrail_blocks_what_the_red_team_set_probes" {
  command = apply

  assert {
    condition = alltrue([
      for f in aws_bedrock_guardrail.support.content_policy_config[0].filters_config :
      f.input_strength == "HIGH" if f.type == "PROMPT_ATTACK"
    ])
    error_message = "The prompt attack filter must run at HIGH on input."
  }

  assert {
    condition     = length([for f in aws_bedrock_guardrail.support.content_policy_config[0].filters_config : f if f.type == "PROMPT_ATTACK"]) == 1
    error_message = "The guardrail must have a prompt attack filter."
  }

  assert {
    condition = contains([
      for e in aws_bedrock_guardrail.support.sensitive_information_policy_config[0].pii_entities_config :
      "${e.type}=${e.action}"
    ], "CREDIT_DEBIT_CARD_NUMBER=BLOCK")
    error_message = "Card numbers must be blocked, not only masked."
  }

  assert {
    condition = contains([
      for e in aws_bedrock_guardrail.support.sensitive_information_policy_config[0].pii_entities_config : e.type
    ], "PHONE")
    error_message = "Phone numbers must be filtered (pii-001 in the red-team set)."
  }

  assert {
    condition     = aws_bedrock_guardrail.support.sensitive_information_policy_config[0].regexes_config[0].pattern == "HG-LOY-[0-9]{4}"
    error_message = "Loyalty IDs must be filtered (pii-004 in the red-team set)."
  }

  assert {
    condition = toset([for t in aws_bedrock_guardrail.support.topic_policy_config[0].topics_config : t.name]) == toset([
      "investment-advice", "medical-advice", "competitor-pricing",
    ])
    error_message = "The denied topics must match the off_topic red-team category."
  }

  assert {
    condition     = aws_bedrock_guardrail.support.kms_key_arn == aws_kms_key.this.arn
    error_message = "The guardrail must be encrypted with the release key."
  }

  assert {
    condition     = startswith(aws_bedrock_guardrail_version.support.description, "config ")
    error_message = "Each guardrail version must carry the fingerprint of the configuration it was published from."
  }

  assert {
    condition     = aws_bedrock_guardrail_version.support.skip_destroy
    error_message = "Published guardrail versions must survive a destroy by default, so rollback targets remain."
  }
}

run "prompt_uses_the_release_candidate_template" {
  command = apply

  assert {
    condition     = strcontains(aws_bedrockagent_prompt.support_answer.variant[0].template_configuration[0].text[0].text, "HG-SYS-7731")
    error_message = "The managed prompt must be the release candidate's template."
  }

  assert {
    condition = toset([
      for v in aws_bedrockagent_prompt.support_answer.variant[0].template_configuration[0].text[0].input_variable : v.name
    ]) == toset(["context", "question"])
    error_message = "The prompt must declare exactly the context and question variables the gate renders."
  }

  assert {
    condition     = aws_bedrockagent_prompt.support_answer.customer_encryption_key_arn == aws_kms_key.this.arn
    error_message = "The prompt must be encrypted with the release key."
  }
}

run "release_parameters_are_encrypted_and_owned_by_the_pipeline" {
  command = apply

  assert {
    condition     = toset(keys(aws_ssm_parameter.release)) == toset(["staging", "prod"])
    error_message = "There must be exactly a staging and a prod alias."
  }

  assert {
    condition     = alltrue([for p in aws_ssm_parameter.release : p.type == "SecureString" && p.key_id == aws_kms_key.this.arn])
    error_message = "Release parameters must be SecureString with the release key."
  }

  assert {
    condition = alltrue([
      for alias, p in aws_ssm_parameter.release :
      "arn:aws:ssm:us-east-1:111122223333:parameter${p.name}" == local.release_parameter_arns[alias]
    ])
    error_message = "The ARNs the role policies grant must be the parameters this stack creates."
  }

  assert {
    condition     = aws_ssm_parameter.release["prod"].name == "/harbor-support/prod/release"
    error_message = "Unexpected parameter name for the prod alias."
  }
}

run "roles_are_scoped_to_one_environment_each" {
  command = apply

  assert {
    condition     = jsondecode(aws_iam_role.gate.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:harbor-goods/support-assistant:environment:genai-staging"
    error_message = "Only the genai-staging environment may assume the gate role."
  }

  assert {
    condition     = jsondecode(aws_iam_role.promote.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:harbor-goods/support-assistant:environment:genai-prod"
    error_message = "Only the genai-prod environment may assume the promote role."
  }

  assert {
    condition     = jsondecode(aws_iam_role.gate.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "The gate role must check the token audience."
  }

  assert {
    condition = alltrue(flatten([
      for doc in [aws_iam_role_policy.gate.policy, aws_iam_role_policy.promote.policy, aws_iam_role_policy.evaluator.policy] : [
        for s in jsondecode(doc).Statement : [for a in flatten([s.Action]) : !endswith(a, "*")]
      ]
    ]))
    error_message = "No wildcard actions in the role policies."
  }

  assert {
    condition = alltrue(flatten([
      for doc in [aws_iam_role_policy.gate.policy, aws_iam_role_policy.promote.policy, aws_iam_role_policy.evaluator.policy] : [
        for s in jsondecode(doc).Statement : [for r in flatten([s.Resource]) : r != "*"]
      ]
    ]))
    error_message = "No role policy statement may apply to every resource."
  }

  assert {
    condition = !anytrue([
      for s in jsondecode(aws_iam_role_policy.gate.policy).Statement :
      contains(flatten([s.Resource]), "arn:aws:ssm:us-east-1:111122223333:parameter/harbor-support/prod/release") && contains(flatten([s.Action]), "ssm:PutParameter")
    ])
    error_message = "The gate role must not be able to write the prod alias."
  }

  assert {
    condition     = jsondecode(aws_iam_role.evaluator.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "111122223333"
    error_message = "The evaluation job role must be assumable only from this account's Bedrock jobs."
  }
}

run "models_outside_the_allowlist_cannot_be_invoked" {
  command = apply

  variables {
    allowed_model_ids = ["amazon.nova-lite-v1:0", "us.anthropic.claude-haiku-4-5-20251001-v1:0"]
  }

  assert {
    condition = toset(one([
      for s in jsondecode(aws_iam_role_policy.gate.policy).Statement : s.Resource if s.Sid == "InvokeAllowlistedModelsOnly"
      ])) == toset([
      "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
      "arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
    ])
    error_message = "The gate role may invoke the allowlisted models (and the judge), nothing else."
  }
}

run "evaluation_bucket_is_private_and_encrypted" {
  command = apply

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.evaluations.block_public_acls,
      aws_s3_bucket_public_access_block.evaluations.block_public_policy,
      aws_s3_bucket_public_access_block.evaluations.ignore_public_acls,
      aws_s3_bucket_public_access_block.evaluations.restrict_public_buckets,
    ])
    error_message = "All four public access blocks must be on."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.evaluations.rule).apply_server_side_encryption_by_default).sse_algorithm == "aws:kms"
    error_message = "Evaluation data must be encrypted with KMS."
  }

  assert {
    condition     = jsondecode(aws_s3_bucket_policy.evaluations.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    error_message = "The bucket policy must deny requests without TLS."
  }

  assert {
    condition     = !aws_s3_bucket.evaluations.force_destroy
    error_message = "Evidence must not be destroyable with the bucket by default."
  }
}

run "guardrail_alarm_watches_the_published_version" {
  command = apply

  assert {
    condition     = aws_cloudwatch_metric_alarm.guardrail_intervention_rate.threshold == 20
    error_message = "Default alarm threshold is 20 percent."
  }

  assert {
    condition     = contains(aws_cloudwatch_metric_alarm.guardrail_intervention_rate.alarm_actions, aws_sns_topic.alarms.arn)
    error_message = "The alarm must notify the alarm topic."
  }

  assert {
    condition     = aws_sns_topic.alarms.kms_master_key_id == aws_kms_key.this.arn
    error_message = "The alarm topic must be encrypted."
  }
}
