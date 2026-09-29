# 0005. Promotion and rollback through SSM Parameter Store aliases

## Status

Accepted

## Context

A release changes configuration, not code: which model, prompt version and guardrail version the assistant uses.
Redeploying the application for each change is slow and couples two release cycles. Rollback has to be fast and must
not depend on the pipeline that produced the bad release.

## Decision

- Each alias (`staging`, `prod`) is a SecureString parameter, `/<name>/<alias>/release`, encrypted with the release
  key. The application reads its alias at start and on a short cache.
- `scripts/promote.sh` writes the serving configuration from `genai-gate serving-config` and labels the new
  parameter version `r-<digest>`.
- `scripts/rollback.sh` writes the previous value as a new version with a `rollback-of-v<N>` label. Nothing is
  deleted.
- The gate role can write only the staging parameter; the promote role only the prod parameter, from the `genai-prod`
  environment, which requires a reviewer.

## Consequences

- Promotion and rollback take seconds and leave an audit trail in the parameter history.
- Parameter history keeps the last 100 versions; older ones rotate out, so long-term evidence stays in the pipeline
  artifacts and the evaluation bucket.
- The application must handle a configuration change at run time, including a guardrail version it has not used.

## Compliance

- `terraform test` asserts the parameters, their encryption and that the gate role cannot write prod.
- `make test-live` promotes twice and rolls back once, then checks the value.

## Notes

Alternative considered: AWS AppConfig with deployment strategies. It adds gradual rollout and automatic rollback on
alarms, and is the next step if Harbor Goods wants canary releases of a configuration.
