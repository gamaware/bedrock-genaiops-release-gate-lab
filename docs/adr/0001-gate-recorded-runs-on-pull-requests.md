# 0001. Gate recorded runs on pull requests, live runs only after merge

## Status

Accepted

## Context

Harbor Goods wants every prompt, model or guardrail change checked before it merges. Running the evaluation sets
against Amazon Bedrock on every pull request would need AWS credentials in pull request jobs, would cost tokens on
every push, and would give slightly different judge scores on each run, so reviewers could not reproduce a verdict.

## Decision

- The pull request check (`offline-gate` in `release-gate.yml`, `make gate` locally) scores a recorded run that the
  pull request carries in `release/candidate/run/`. It has no AWS access.
- The same gate code scores a fresh run in the live gate, which runs only after merge, from the `genai-staging`
  GitHub environment, with short-lived OIDC credentials.
- A run is recorded by `genai-gate collect --live` (the live gate or `make test-live`) and committed with the change
  that produced it.

## Consequences

- Pull request verdicts are reproducible byte for byte, and `report/evidence/` can be checked for drift in CI.
- Pull request jobs never hold credentials, so a malicious pull request cannot reach the account.
- A recorded run can be out of date with the release it claims to cover. ADR 0002 binds them by digest.
- The live gate can still block a change that passed offline, for example when the model behaves differently today.
  That is the point of running it before promotion.

## Compliance

- zizmor and Checkov check the workflows; the `offline-gate` job has only `contents: read`.
- `tests/test_scenarios.py` runs every recorded scenario through the CLI.

## Notes

Alternative considered: live evaluation on every pull request with a cheap model. Rejected for the credential exposure
and for verdicts that change between reruns of the same commit.
