# 0007. Guardrail text units count toward the cost budget

## Status

Accepted

## Context

A cost check that counts only model tokens misses a large part of the bill. With Amazon Nova Lite and four guardrail
policies, the guardrail is about 85% of the cost per request in the recorded runs: each text unit (up to 1,000
characters) is billed once per policy that evaluates it.

## Decision

- The cost check adds model tokens at the prices in `gate/models.yaml` and guardrail text units at the per-policy
  prices, for the policies the release enables.
- The budget is absolute (USD per 1,000 requests) and relative (maximum increase against the baseline).
- The evidence reports the guardrail's share of the cost.

## Consequences

- Switching to a cheaper model saves little while the guardrail dominates, which the evidence shows (scenario
  `model-swap-quality-regression`: 7% saving).
- The model is simplified: it bills every enabled policy on input and output. A client that enables some policies on
  one side only should model that, or measure it from the `usage` field of ApplyGuardrail.
- Prices change; `gate/models.yaml` is updated in a reviewed pull request.

## Compliance

- `tests/test_checks.py` checks the formula and the guardrail share.

## Notes

None.
