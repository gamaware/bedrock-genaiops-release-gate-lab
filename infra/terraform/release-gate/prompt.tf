# The draft prompt in Prompt Management. The live gate publishes a numbered
# version from it (CreatePromptVersion), and release.yaml pins that number.
resource "aws_bedrockagent_prompt" "support_answer" {
  name                        = "${var.name}-support-answer"
  description                 = "Harbor Goods support answer, grounded on retrieved policy text."
  customer_encryption_key_arn = aws_kms_key.this.arn
  default_variant             = "default"

  variant {
    name          = "default"
    model_id      = var.prompt_model_id
    template_type = "TEXT"

    inference_configuration {
      text {
        max_tokens  = 400
        temperature = 0.2
        top_p       = 0.9
      }
    }

    template_configuration {
      text {
        text = local.prompt_template

        input_variable {
          name = "context"
        }
        input_variable {
          name = "question"
        }
      }
    }
  }
}
