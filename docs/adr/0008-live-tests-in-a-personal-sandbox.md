# 0008. Live tests only in a personal sandbox account

## Status

Accepted

## Context

`make test-live` proves what the offline checks cannot: that the roles, guardrail, prompt and parameters work
against the real APIs. It creates resources and spends tokens, so it must never run in a shared or client account, and
it must not leave anything behind.

## Decision

- The script uses the `personal` AWS CLI profile only and refuses to run unless the account matches
  `LIVE_ACCOUNT_ID`, which the maintainer sets locally and never commits.
- It creates nothing public: no endpoints, no public bucket, no DNS. The evaluation bucket blocks public access.
- Every resource is tagged `Project=bedrock-genaiops-release-gate-lab`, `Ephemeral=true` and a run ID. A trap destroys
  the stack on success, failure or interruption and lists anything still tagged with the run.
- Amazon Nova Lite is the model and the judge, to keep a run to cents.

## Consequences

- The live test depends on the account's GitHub OIDC provider existing (the roles trust it).
- Model access for Anthropic models needs a one-time form; the live test avoids them.

## Compliance

- Review of `scripts/test-live.sh` (shellcheck and shellharden in `make verify`).

## Notes

None.
