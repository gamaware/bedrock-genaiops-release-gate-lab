# 0002. One release file, bound to its evidence by digest

## Status

Accepted

## Context

An answer depends on the model and its inference settings, the prompt version and text, the guardrail version and
the knowledge base with its chunking. When these live in different places (console, application config, Terraform),
nobody can say which combination served an answer, and evidence recorded for one combination can be presented for
another.

## Decision

- `release.yaml` pins all of them, validated by `src/genai_gate/release.schema.json`.
- The prompt text sits next to the release file, and `template_sha256` pins it. Editing the text without a new pin is
  a release problem.
- The release digest is the SHA-256 of the canonical JSON of the release file. Each run manifest (`run.json`) records
  the digest of the release it was produced for, and the digests of the golden and red-team sets it used.
- The gate blocks when the candidate or the baseline evidence does not match its release or the current sets.

## Consequences

- A reviewer sees exactly what changed (the "What changed" table in the evidence) and that the evidence covers it.
- Any change to the sets forces new recorded runs for both baseline and candidate.
- The serving configuration promoted through SSM carries the same digest, so production can be traced back to the
  evidence that approved it.

## Compliance

- Scenario `stale-evidence` and the unit tests in `tests/test_inputs.py`.

## Notes

The knowledge base ID and chunking are pinned but not re-ingested by this lab;
[terraform-aws-bedrock-rag-lab](https://github.com/gamaware/terraform-aws-bedrock-rag-lab) owns the knowledge base.
