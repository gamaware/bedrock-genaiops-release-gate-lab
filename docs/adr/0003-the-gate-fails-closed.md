# 0003. The gate fails closed

## Status

Accepted

## Context

A release gate that passes when something goes wrong is worse than none, because it produces a green check.
Typical failures: a judge reply that is not JSON, a missing answer, a run that covers fewer questions than the set,
a model without a price, a policy file with a typo.

## Decision

- Loaders reject anything malformed, incomplete or inconsistent with `EvidenceError` or `ConfigError`.
- The CLI exits 0 for PASS, 1 for BLOCK and 2 for invalid input or incomplete evidence. The pipeline treats anything
  but 0 as blocked.
- Missing prices, missing categories in the policy (treated as a 100% requirement) and an unpriced baseline all
  block rather than skip a check.
- Known failures inside the policy's tolerance, such as a red-team prompt the baseline also fails, are reported as
  notes, so they stay visible without blocking every release.

## Consequences

- Operators occasionally see a block that is a data problem, not a quality problem. The message says which.
- The judge must return strict JSON; the live adapter rejects anything else.

## Compliance

- `tests/test_inputs.py`, `tests/test_cli.py` and the judge tests in `tests/test_collect_live.py`.

## Notes

None.
