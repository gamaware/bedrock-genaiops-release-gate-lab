# Copilot code review instructions

When reviewing pull requests in this repository:

- The release gate must fail closed. Flag any change that lets missing, malformed or stale evidence pass.
- A change to `gate/policy.yaml` or `gate/models.yaml` must come with regenerated `report/evidence/` files.
- Pinned guardrail and prompt versions must be numbers, never `DRAFT`.
- Pull request workflows must not request `id-token: write` or read AWS secrets.
- Actions must be pinned by full commit SHA with the version in a comment.
- New Terraform behaviour needs an assertion in a `.tftest.hcl` file that runs against the mocked provider.
- Flag any suppressed lint rule or scanner skip that lacks a reason next to the code.
- Only fictional names and AWS documentation example account IDs may appear; no real IDs, ARNs, IPs or emails.
- Verify conventional commit format in PR titles.
