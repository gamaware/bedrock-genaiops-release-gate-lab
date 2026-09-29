# Architecture decision records

Architecture decision records follow the *Fundamentals of Software Architecture* (2nd ed.) format.
Records are never deleted; a replaced decision is marked Superseded and links to its successor.

| Number | Title | Status |
| --- | --- | --- |
| [0001](0001-gate-recorded-runs-on-pull-requests.md) | Gate recorded runs on pull requests, live runs only after merge | Accepted |
| [0002](0002-one-release-file-bound-by-digest.md) | One release file, bound to its evidence by digest | Accepted |
| [0003](0003-the-gate-fails-closed.md) | The gate fails closed | Accepted |
| [0004](0004-deterministic-red-team-llm-judge-for-quality.md) | Deterministic red-team scoring, LLM judge for quality only | Accepted |
| [0005](0005-promotion-through-ssm-aliases.md) | Promotion and rollback through SSM Parameter Store aliases | Accepted |
| [0006](0006-numbered-versions-only.md) | Numbered prompt and guardrail versions only | Accepted |
| [0007](0007-guardrail-units-in-the-cost-budget.md) | Guardrail text units count toward the cost budget | Accepted |
| [0008](0008-live-tests-in-a-personal-sandbox.md) | Live tests only in a personal sandbox account | Accepted |
