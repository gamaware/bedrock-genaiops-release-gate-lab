# release-gate stack

Serving configuration and pipeline access for the Harbor Goods support assistant: the guardrail and its numbered
version, the managed prompt, the SSM staging and prod aliases, the KMS key, the evaluation bucket, the gate, promote
and evaluator roles, and the guardrail intervention alarm.

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in the repository and OIDC provider
terraform init -backend-config=...              # see backend.tf.example
terraform apply
```

Set the outputs `gate_role_arn` and `promote_role_arn` as the repository variables `AWS_GATE_ROLE_ARN` and
`AWS_PROMOTE_ROLE_ARN`, and pin `guardrail_id`, `guardrail_version` and `prompt_arn` in `release.yaml`.

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| terraform | >= 1.11.0, < 2.0.0 |
| aws | ~> 6.66 |

## Providers

| Name | Version |
| ---- | ------- |
| aws | 6.66.0 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_bedrock_guardrail.support](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail) | resource |
| [aws_bedrock_guardrail_version.support](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail_version) | resource |
| [aws_bedrockagent_prompt.support_answer](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_prompt) | resource |
| [aws_cloudwatch_metric_alarm.guardrail_intervention_rate](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_iam_role.evaluator](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.gate](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.promote](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.evaluator](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.gate](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.promote](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_kms_alias.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |
| [aws_s3_bucket.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_lifecycle_configuration.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_ownership_controls.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_policy.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.evaluations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_sns_topic.alarms](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic) | resource |
| [aws_ssm_parameter.release](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ssm_parameter) | resource |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| github\_oidc\_provider\_arn | ARN of the account's GitHub OIDC identity provider (created once per account, see github-actions-aws-oidc-lab). | `string` | n/a | yes |
| github\_repository | GitHub repository (owner/name) whose release-gate workflow may assume the gate and promote roles. | `string` | n/a | yes |
| allowed\_model\_ids | Models a release may pin. Keep in step with gate/models.yaml; the roles can invoke only these and the judge. | `list(string)` | ```[ "amazon.nova-micro-v1:0", "amazon.nova-lite-v1:0", "us.anthropic.claude-haiku-4-5-20251001-v1:0" ]``` | no |
| evaluation\_retention\_days | Days to keep evaluation datasets and results in the evaluation bucket. | `number` | `90` | no |
| force\_destroy | Allow destroying the evaluation bucket with objects in it. Only the live test sets true. | `bool` | `false` | no |
| guardrail\_intervention\_alarm\_pct | Alarm when this share of guardrail evaluations intervene, sustained for 15 minutes. | `number` | `20` | no |
| judge\_model\_id | Model that scores answers (LLM-as-judge) in the live gate and in evaluation jobs. | `string` | `"amazon.nova-lite-v1:0"` | no |
| name | Prefix for every resource name. | `string` | `"harbor-support"` | no |
| prompt\_model\_id | Model the managed prompt's variant targets. Must be in allowed\_model\_ids. | `string` | `"amazon.nova-lite-v1:0"` | no |
| prompt\_template\_file | Prompt template to publish to Prompt Management, relative to this stack. Defaults to the release candidate. | `string` | `"../../../release/candidate/prompt.txt"` | no |
| region | AWS Region for the serving configuration and the evaluation jobs. | `string` | `"us-east-1"` | no |
| retain\_guardrail\_versions | Keep published guardrail versions on destroy, so a rollback target never disappears. The live test sets false. | `bool` | `true` | no |
| tags | Extra tags for every resource. | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| alarm\_topic\_arn | SNS topic for the guardrail alarm; subscribe the on-call channel. |
| evaluation\_bucket | Bucket for evaluation datasets, job results and release evidence. |
| evaluator\_role\_arn | Service role to pass to Amazon Bedrock evaluation jobs. |
| gate\_role\_arn | Set as the AWS\_GATE\_ROLE\_ARN variable of the genai-staging GitHub environment. |
| guardrail\_id | Guardrail ID to pin in release.yaml. |
| guardrail\_version | Latest published guardrail version, to pin in release.yaml. |
| promote\_role\_arn | Set as the AWS\_PROMOTE\_ROLE\_ARN variable of the genai-prod GitHub environment. |
| prompt\_arn | Managed prompt ARN to pin in release.yaml (with a version the live gate publishes). |
| release\_parameters | SSM parameter per alias (staging, prod) holding the serving configuration. |
<!-- END_TF_DOCS -->
