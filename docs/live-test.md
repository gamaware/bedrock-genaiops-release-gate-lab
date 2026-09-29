# Live test

`make test-live` runs the whole path against real AWS APIs, then destroys everything. It is manual and runs only in
the maintainer's personal sandbox account ([ADR 0008](adr/0008-live-tests-in-a-personal-sandbox.md)).

## Prerequisites

- AWS CLI profile `personal`, signed in.
- `LIVE_ACCOUNT_ID` exported with that account's ID. The script refuses any other account.
- The account's GitHub OIDC provider (`token.actions.githubusercontent.com`), which `github-actions-aws-oidc-lab`
  creates. The roles trust it; the test does not assume them.
- Model access to Amazon Nova Lite in `us-east-1` (on by default in most accounts).
- An AWS Budget alert on the account is recommended before the first run.

## What it does

1. Shows the caller identity and asks for confirmation (`LIVE_YES=1` skips it).
2. Applies `infra/terraform/release-gate` from a temporary copy with a run-specific name, tagged
   `Project=bedrock-genaiops-release-gate-lab`, `Ephemeral=true` and `run=<id>`.
3. Publishes a prompt version and writes a release file that pins it and the guardrail version Terraform published.
4. Records a live run: the 12 golden questions and 12 red-team prompts go through ApplyGuardrail and Converse with
   Nova Lite, and Nova Lite judges the answers.
5. Runs the gate against the committed production baseline and prints the evidence. A BLOCK is reported, not
   treated as a failure: live scores differ from the recorded fixtures. Invalid evidence fails the test.
6. Promotes the production release file to the staging alias, promotes the candidate, rolls back, and checks that
   the parameter holds the first value again.
7. Destroys the stack on exit, even after a failure or Ctrl-C, and lists anything still tagged with the run.

## Cost

About USD 0.05 to 0.20 per run: tokens for 24 prompts and 12 judge calls, guardrail text units, and API calls. The
KMS key is scheduled for deletion (7 days) and costs nothing while pending.

## Run

```bash
export LIVE_ACCOUNT_ID=111122223333   # your sandbox account; AWS documentation example shown
make test-live
```
