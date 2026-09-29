# 0007. Guardrail text units count toward the cost budget

## Status

Accepted

## Context

A cost check that counts only model tokens misses a large part of the bill. With Amazon Nova Lite and four guardrail
policies, the guardrail is about 85% of the cost per request in the recorded runs: each text unit (up to 1,000
characters) is billed once per policy that evaluates it.

## Decision

- The cost check adds model tokens at the prices in `gate/models.yaml` and, for each guardrail policy, the text units
  that policy was billed for (the `usage` field of ApplyGuardrail, recorded per policy in `guardrail_units`) at its
  price. A policy that evaluated nothing, such as contextual grounding on an input, costs nothing.
- Billed usage the catalog cannot price fails the run instead of counting as free.
- The budget is absolute (USD per 1,000 requests) and relative (maximum increase against the baseline).
- The evidence reports the guardrail's share of the cost.

## Consequences

- Switching to a cheaper model saves little while the guardrail dominates, which the evidence shows (scenario
  `model-swap-quality-regression`: 7% saving).
- Recorded runs carry per-policy units, so enabling a policy on one side only shows up in the cost directly.
- Prices change; `gate/models.yaml` is updated in a reviewed pull request.

## Compliance

- `tests/test_checks.py` checks the formula and the guardrail share.

## Notes

None.
