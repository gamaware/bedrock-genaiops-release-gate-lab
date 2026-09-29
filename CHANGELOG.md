# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `genai-gate` Python CLI: `validate`, `evaluate`, `collect --live`, `serving-config` and `check-baseline`, with exit
  codes 0 (PASS), 1 (BLOCK) and 2 (invalid input or incomplete evidence).
- Four checks: release integrity (schema, model allowlist, template hash, evidence bound by release and set digests),
  quality (LLM-judge means, drop against the baseline, critical questions, item regressions), red team (per-category
  pass rates, regressions against the baseline) and cost and latency (model tokens plus guardrail units billed per
  policy, p95 of end-to-end latency including both guardrail calls).
- Release evidence in Markdown and JSON, deterministic for the same inputs.
- Amazon Bedrock adapters for GetPrompt (the pinned prompt version, hash-checked), Retrieve (the pinned knowledge
  base), Converse, ApplyGuardrail (grounding source and query qualified for contextual grounding) and an LLM judge,
  tested through botocore's Stubber.
- The live gate blocks unless `release/production` is the release the prod alias serves.
- Evaluation sets: 12 golden questions (3 critical), 12 red-team prompts in three categories, and the judge rubric.
- Recorded production baseline, release candidate and six scenarios with expected verdicts.
- Terraform stack: guardrail and numbered version, managed prompt, SSM staging and prod aliases, KMS key, evaluation
  bucket, gate, promote and evaluator roles, guardrail intervention alarm, with mocked `terraform test` suites.
- Workflows: `ci.yml` (`make verify` next to the shared checks), `release-gate.yml` (offline gate, live gate, approved
  promotion), `rollback.yml`, `scorecard.yml`.
- Promotion and rollback scripts, live test for a personal sandbox account, sample client report and eight ADRs.

### Security

- Shared reusable workflows from `gamaware/.github` are called pinned to a full commit SHA.
