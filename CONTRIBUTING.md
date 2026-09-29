# Contributing

1. Install the tools listed in the README and run `pre-commit install`.
2. Work on a branch; `main` is protected.
3. Keep the gate failing closed: a new rule needs a unit test, and a rule that changes a verdict needs a scenario in
   `fixtures/scenarios/` with `expected.json`.
4. After changing `gate/`, `evals/` or `fixtures/`, run `make evidence` and commit `report/evidence/`.
5. After changing `report/REPORT.md`, run `make report` (needs Docker) and commit the PDF and `REPORT.sha256`.
6. Run `make verify` before opening a pull request. It must end with `verify: all checks passed`.
7. Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `refactor:`, `test:`).
