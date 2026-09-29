variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "harbor-support"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "name must be 3 to 31 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "region" {
  description = "AWS Region for the serving configuration and the evaluation jobs."
  type        = string
  default     = "us-east-1"
}

variable "github_repository" {
  description = "GitHub repository (owner/name) whose release-gate workflow may assume the gate and promote roles."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be owner/name."
  }
}

variable "github_oidc_provider_arn" {
  description = "ARN of the account's GitHub OIDC identity provider (created once per account, see github-actions-aws-oidc-lab)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.github_oidc_provider_arn))
    error_message = "github_oidc_provider_arn must be the ARN of the token.actions.githubusercontent.com provider."
  }
}

variable "allowed_model_ids" {
  description = "Models a release may pin. Keep in step with gate/models.yaml; the roles can invoke only these and the judge."
  type        = list(string)
  default = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  ]

  validation {
    condition     = length(var.allowed_model_ids) > 0 && alltrue([for id in var.allowed_model_ids : can(regex("^((us|eu|global)\\.)?[a-z0-9-]+\\.[a-z0-9.:-]+$", id))])
    error_message = "allowed_model_ids must list at least one Amazon Bedrock model or inference profile ID."
  }
}

variable "prompt_model_id" {
  description = "Model the managed prompt's variant targets. Must be in allowed_model_ids."
  type        = string
  default     = "amazon.nova-lite-v1:0"

  validation {
    condition     = contains(var.allowed_model_ids, var.prompt_model_id)
    error_message = "prompt_model_id must be one of allowed_model_ids."
  }
}

variable "judge_model_id" {
  description = "Model that scores answers (LLM-as-judge) in the live gate and in evaluation jobs."
  type        = string
  default     = "amazon.nova-lite-v1:0"
}

variable "knowledge_base_id" {
  description = "ID of the existing knowledge base the release pins (knowledge_base.id in release.yaml). The gate role may query only this one."
  type        = string
  default     = "HGPOLICYKB"

  validation {
    condition     = can(regex("^[0-9A-Za-z]{10}$", var.knowledge_base_id))
    error_message = "knowledge_base_id must be a 10-character Amazon Bedrock knowledge base ID."
  }
}

variable "prompt_template_file" {
  description = "Prompt template to publish to Prompt Management, relative to this stack. Defaults to the release candidate."
  type        = string
  default     = "../../../release/candidate/prompt.txt"
}

variable "guardrail_intervention_alarm_pct" {
  description = "Alarm when this share of guardrail evaluations intervene, sustained for 15 minutes."
  type        = number
  default     = 20

  validation {
    condition     = var.guardrail_intervention_alarm_pct > 0 && var.guardrail_intervention_alarm_pct <= 100
    error_message = "guardrail_intervention_alarm_pct must be between 0 (exclusive) and 100."
  }
}

variable "retain_guardrail_versions" {
  description = "Keep published guardrail versions on destroy, so a rollback target never disappears. The live test sets false."
  type        = bool
  default     = true
}

variable "evaluation_retention_days" {
  description = "Days to keep evaluation datasets and results in the evaluation bucket."
  type        = number
  default     = 90

  validation {
    condition     = var.evaluation_retention_days >= 30
    error_message = "Keep release evidence for at least 30 days."
  }
}

variable "force_destroy" {
  description = "Allow destroying the evaluation bucket with objects in it. Only the live test sets true."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
