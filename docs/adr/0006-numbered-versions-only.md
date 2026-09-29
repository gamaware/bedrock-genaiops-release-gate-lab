# 0006. Numbered prompt and guardrail versions only

## Status

Accepted

## Context

Prompt Management and Guardrails both have a working draft (`DRAFT`) and immutable numbered versions. The draft
changes whenever someone edits it, so a release that points at it has no stable meaning.

## Decision

- The release schema accepts only numeric versions for the prompt and the guardrail.
- Terraform publishes a guardrail version whose description carries a fingerprint of the configuration, so a
  configuration change publishes a new version. The live gate publishes a prompt version (`CreatePromptVersion`).
- Published guardrail versions survive `terraform destroy` by default (`retain_guardrail_versions`), so rollback
  targets never disappear. The live test sets it to false to clean up.

## Consequences

- Versions accumulate; deleting old ones is a manual clean-up once no parameter history refers to them.

## Compliance

- Schema test in `tests/test_inputs.py`; `terraform test` asserts the version fingerprint and `skip_destroy`.

## Notes

None.
