# Runbook: support assistant releases

Operating guide for the Harbor Goods platform team. Commands assume the repository root and, for AWS steps, the
role of the GitHub environment named in each section.

## Propose a change

1. Change what you need: `release/candidate/prompt.txt`, the model or inference settings, the guardrail version, or
   the chunking in `release/candidate/release.yaml`. If you edit the prompt text, update `template_sha256`
   (`shasum -a 256 release/candidate/prompt.txt`) and bump `prompt.version` after the live gate publishes it.
2. Record a run for the candidate: run the live gate from a branch in a sandbox, or `make test-live`, and copy the
   run directory to `release/candidate/run/`. The run manifest must carry the new release digest.
3. Run `make gate`. Open the pull request; the `offline-gate` job posts the evidence to the job summary.

## Read the evidence

The evidence starts with the verdict and a "What changed" table. Each check lists its measures against the baseline
and the limit, then the findings that block and the notes that do not. A block names the question or prompt ID;
look it up in `evals/`.

| Check | Typical block | What to do |
| --- | --- | --- |
| release | Stale evidence, model not allowlisted, template edited without a new pin | Re-record the run, or add the model to `gate/models.yaml` in its own reviewed pull request |
| quality | Mean below the minimum, drop against the baseline, a critical question below 4 | Read the judge rationale for the named questions; fix the prompt or keep the old model |
| red team | Regression on a prompt the baseline handled | Never loosen the policy to pass; restore the guardrail setting or add a refusal instruction |
| cost and latency | Over budget or more than 25% more expensive | Check the guardrail share first; it usually dominates |

## Release

1. Merge the pull request.
2. Run the `release-gate` workflow on `main` (Actions, Run workflow). The live gate first checks that
   `release/production` is the release the prod alias serves (its digest against the parameter's `release_digest`)
   and blocks if not. It then records a fresh run, gates it and, on PASS, writes the staging alias.
3. Review the `release-evidence-live` artifact and the staging behaviour. Approve the `genai-prod` deployment to
   promote.
4. Move the baseline: in a pull request, copy `release/candidate/` (release file, prompt and recorded run) to
   `release/production/`. Until then the next live gate blocks, so no candidate is ever compared with a release
   customers no longer get.

## Roll back

Run the `rollback` workflow on `main` and approve it in `genai-prod`. It restores the previous prod value from the
parameter history and labels the new version `rollback-of-v<N>`. Then restore `release/production/` to the release
prod serves again (from git history); the live gate blocks until the baseline matches. From a terminal with the
promote role:

```bash
AWS_REGION=us-east-1 scripts/rollback.sh prod
aws ssm get-parameter-history --name /harbor-support/prod/release --with-decryption \
  --query 'Parameters[-3:].[Version,Labels,Value]'
```

## Guardrail intervention alarm

The alarm `harbor-support-guardrail-intervention-rate` fires when more than 20% of guardrail evaluations intervene
for 15 minutes.

1. Check whether a release went out in the last hours: the prod parameter history shows the version and its
   `r-<digest>` label.
2. If yes and customers report blocked normal questions, roll back, then add the blocked questions to the golden set.
3. If no release went out, look for an attack: the guardrail's CloudWatch metrics by policy type show which policy
   intervenes. Keep the guardrail as it is and tell security.

## Update prices or thresholds

Change `gate/models.yaml` or `gate/policy.yaml` in a pull request of its own, run `make evidence`, and commit the
regenerated `report/evidence/` so reviewers see which verdicts the change moves.
