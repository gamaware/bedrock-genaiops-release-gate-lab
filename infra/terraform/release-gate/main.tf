data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region

  # GitHub environments that map to the two roles. Protect both in the
  # repository settings; genai-prod needs a required reviewer.
  environments = {
    staging = "genai-staging"
    prod    = "genai-prod"
  }

  # Built from the names, so policies and tests do not depend on computed ARNs.
  release_parameter_arns = {
    for alias, _ in local.environments :
    alias => "arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter/${var.name}/${alias}/release"
  }

  model_ids = distinct(concat(var.allowed_model_ids, [var.judge_model_id]))

  # Cross-Region inference profiles (us., eu., global.) need the profile ARN
  # and the foundation model in every Region the profile routes to.
  model_arns = flatten([
    for id in local.model_ids : can(regex("^(us|eu|global)\\.", id)) ? [
      "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:inference-profile/${id}",
      "arn:${local.partition}:bedrock:*::foundation-model/${replace(id, "/^(us|eu|global)\\./", "")}",
      ] : [
      "arn:${local.partition}:bedrock:${local.region}::foundation-model/${id}",
    ]
  ])

  prompt_template = file("${path.module}/${var.prompt_template_file}")
}
