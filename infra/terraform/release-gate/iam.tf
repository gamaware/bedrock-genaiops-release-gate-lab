# Three roles, each scoped to one job:
#   gate      GitHub environment genai-staging: run the live gate against staging
#   promote   GitHub environment genai-prod: write the prod alias, read history to roll back
#   evaluator Amazon Bedrock service role for model evaluation jobs
# Pull request workflows get none of them (no id-token permission).

locals {
  oidc_audience = "token.actions.githubusercontent.com:aud"
  oidc_subject  = "token.actions.githubusercontent.com:sub"

  kms_use = {
    Sid      = "UseTheReleaseKey"
    Effect   = "Allow"
    Action   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    Resource = aws_kms_key.this.arn
  }

  gate_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeAllowlistedModelsOnly"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = local.model_arns
      },
      {
        Sid      = "ApplyTheSupportGuardrail"
        Effect   = "Allow"
        Action   = ["bedrock:ApplyGuardrail"]
        Resource = [aws_bedrock_guardrail.support.guardrail_arn]
      },
      {
        Sid      = "ReadAndVersionTheSupportPrompt"
        Effect   = "Allow"
        Action   = ["bedrock:GetPrompt", "bedrock:CreatePromptVersion"]
        Resource = [aws_bedrockagent_prompt.support_answer.arn, "${aws_bedrockagent_prompt.support_answer.arn}:*"]
      },
      {
        Sid    = "RunEvaluationJobs"
        Effect = "Allow"
        Action = ["bedrock:CreateEvaluationJob", "bedrock:GetEvaluationJob", "bedrock:StopEvaluationJob"]
        Resource = [
          "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:evaluation-job/*",
        ]
      },
      {
        Sid      = "PassOnlyTheEvaluatorRoleToBedrock"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.evaluator.arn]
        Condition = {
          StringEquals = { "iam:PassedToService" = "bedrock.amazonaws.com" }
        }
      },
      {
        Sid      = "WriteEvaluationData"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.evaluations.arn}/*"]
      },
      {
        Sid      = "ListEvaluationData"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.evaluations.arn]
      },
      {
        Sid      = "PromoteToStaging"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:PutParameter"]
        Resource = [local.release_parameter_arns.staging]
      },
      {
        Sid      = "ReadTheProductionBaseline"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [local.release_parameter_arns.prod]
      },
      local.kms_use,
    ]
  }

  promote_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadTheStagedRelease"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [local.release_parameter_arns.staging]
      },
      {
        Sid    = "PromoteAndRollBackProduction"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameterHistory",
          "ssm:PutParameter",
          "ssm:LabelParameterVersion",
        ]
        Resource = [local.release_parameter_arns.prod]
      },
      local.kms_use,
    ]
  }

  evaluator_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadDatasetsWriteResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.evaluations.arn}/*"]
      },
      {
        Sid      = "ListTheBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.evaluations.arn]
      },
      {
        Sid      = "InvokeAllowlistedModelsAndTheJudge"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.model_arns
      },
      local.kms_use,
    ]
  }
}


resource "aws_iam_role" "gate" {
  name                 = "${var.name}-release-gate"
  description          = "Live release gate from the ${local.environments.staging} GitHub environment"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = var.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          (local.oidc_audience) = "sts.amazonaws.com"
          (local.oidc_subject)  = "repo:${var.github_repository}:environment:${local.environments.staging}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gate" {
  name   = "release-gate"
  role   = aws_iam_role.gate.id
  policy = jsonencode(local.gate_policy)
}

resource "aws_iam_role" "promote" {
  name                 = "${var.name}-release-promote"
  description          = "Promotion and rollback from the ${local.environments.prod} GitHub environment"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = var.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          (local.oidc_audience) = "sts.amazonaws.com"
          (local.oidc_subject)  = "repo:${var.github_repository}:environment:${local.environments.prod}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "promote" {
  name   = "release-promote"
  role   = aws_iam_role.promote.id
  policy = jsonencode(local.promote_policy)
}

resource "aws_iam_role" "evaluator" {
  name        = "${var.name}-evaluation-jobs"
  description = "Service role for Amazon Bedrock model evaluation jobs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:evaluation-job/*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "evaluator" {
  name   = "evaluation-jobs"
  role   = aws_iam_role.evaluator.id
  policy = jsonencode(local.evaluator_policy)
}
