# Offline: the mocked provider never calls AWS and needs no credentials.
# Account 111122223333 is the AWS documentation example ID.
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
}

variables {
  github_repository        = "harbor-goods/support-assistant"
  github_oidc_provider_arn = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
}

# Inputs that must be rejected before anything is planned.

run "rejects_a_prompt_model_outside_the_allowlist" {
  command = plan

  variables {
    prompt_model_id = "anthropic.claude-3-5-sonnet-20240620-v1:0"
  }

  expect_failures = [var.prompt_model_id]
}

run "rejects_an_empty_allowlist" {
  command = plan

  variables {
    allowed_model_ids = []
    prompt_model_id   = "amazon.nova-lite-v1:0"
  }

  expect_failures = [var.allowed_model_ids]
}

run "rejects_a_repository_without_an_owner" {
  command = plan

  variables {
    github_repository = "support-assistant"
  }

  expect_failures = [var.github_repository]
}

run "rejects_an_oidc_provider_other_than_github" {
  command = plan

  variables {
    github_oidc_provider_arn = "arn:aws:iam::111122223333:oidc-provider/gitlab.example.com"
  }

  expect_failures = [var.github_oidc_provider_arn]
}

run "rejects_a_retention_too_short_for_audit" {
  command = plan

  variables {
    evaluation_retention_days = 7
  }

  expect_failures = [var.evaluation_retention_days]
}

run "rejects_an_alarm_threshold_out_of_range" {
  command = plan

  variables {
    guardrail_intervention_alarm_pct = 0
  }

  expect_failures = [var.guardrail_intervention_alarm_pct]
}
