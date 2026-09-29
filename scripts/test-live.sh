#!/usr/bin/env bash
# Manual end-to-end test in the maintainer's personal sandbox account (make test-live).
# Never runs in CI and never in a shared or client account.
#
# 1. Refuses to run unless the AWS CLI profile is "personal" and its account is
#    the one in LIVE_ACCOUNT_ID (set by the maintainer, never committed).
# 2. Applies infra/terraform/release-gate from a temporary copy, tagged
#    Project=bedrock-genaiops-release-gate-lab and Ephemeral=true.
# 3. Publishes a prompt version, writes a release file that pins it and the
#    guardrail version Terraform published, records a live run (Converse and
#    ApplyGuardrail, Nova Lite as model and judge) and runs the gate on it.
# 4. Promotes to the staging alias twice and rolls back once, then checks the
#    parameter holds the first value again.
# 5. Destroys everything on exit (success, failure or Ctrl-C) and lists any
#    resource still tagged with this run.
#
# Creates nothing public: no endpoints, no public bucket, no DNS.
# Cost: about USD 0.05 to 0.20 per run (tokens for 24 prompts plus judge calls,
# guardrail text units, KMS key pending deletion is free). Needs the account's
# GitHub OIDC provider (github-actions-aws-oidc-lab creates it).
#
# Env: LIVE_ACCOUNT_ID (required), LIVE_REGION (default us-east-1),
#      LIVE_YES=1 skips the confirmation prompt.
set -euo pipefail

PROFILE="personal"
REGION="${LIVE_REGION:-us-east-1}"
PROJECT="bedrock-genaiops-release-gate-lab"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
RUN_ID="$(date +%s | tail -c 7)"
NAME="hg-gate-$RUN_ID"
WORK="$(mktemp -d)"

: "${LIVE_ACCOUNT_ID:?set LIVE_ACCOUNT_ID to the personal sandbox account ID}"

aws_cli() {
  aws --profile "$PROFILE" --region "$REGION" "$@"
}

echo "Account for this run (profile $PROFILE):"
aws sts get-caller-identity --profile "$PROFILE" --output table
account_id="$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)"
if [ "$account_id" != "$LIVE_ACCOUNT_ID" ]; then
  echo "refusing: profile $PROFILE is account $account_id, not LIVE_ACCOUNT_ID" >&2
  exit 1
fi
oidc_arn="arn:aws:iam::$account_id:oidc-provider/token.actions.githubusercontent.com"
if ! aws_cli iam get-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" > /dev/null 2>&1; then
  echo "refusing: the GitHub OIDC provider does not exist in this account" >&2
  exit 1
fi
if [ "${LIVE_YES:-0}" != "1" ]; then
  read -r -p "Create, test and destroy $NAME in $REGION on this account? [y/N] " answer
  [ "$answer" = "y" ] || exit 1
fi

export AWS_PROFILE="$PROFILE"
export AWS_REGION="$REGION"
export TF_IN_AUTOMATION=1
export GENAI_NAME="$NAME"

cp -R "$REPO_ROOT/infra" "$WORK/infra"
cp -R "$REPO_ROOT/release" "$WORK/release"
rm -rf "$WORK"/infra/terraform/*/.terraform "$WORK"/infra/terraform/*/terraform.tfstate*
STACK="$WORK/infra/terraform/release-gate"
TF_VARS=(
  -var "name=$NAME"
  -var "region=$REGION"
  -var "github_repository=example-org/$PROJECT"
  -var "github_oidc_provider_arn=$oidc_arn"
  -var retain_guardrail_versions=false
  -var force_destroy=true
  -var "tags={\"Project\"=\"$PROJECT\",\"Ephemeral\"=\"true\",\"run\"=\"$RUN_ID\"}"
)

cleanup() {
  local code=$?
  echo "--- destroy"
  terraform -chdir="$STACK" destroy -auto-approve -input=false "${TF_VARS[@]}" || code=1
  echo "--- resources still tagged run=$RUN_ID (expect none):"
  aws_cli resourcegroupstaggingapi get-resources --tag-filters "Key=run,Values=$RUN_ID" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text || true
  rm -rf "$WORK"
  exit "$code"
}
trap cleanup EXIT

echo "--- apply"
terraform -chdir="$STACK" init -input=false > /dev/null
terraform -chdir="$STACK" apply -auto-approve -input=false "${TF_VARS[@]}"

prompt_arn="$(terraform -chdir="$STACK" output -raw prompt_arn)"
guardrail_id="$(terraform -chdir="$STACK" output -raw guardrail_id)"
guardrail_version="$(terraform -chdir="$STACK" output -raw guardrail_version)"
prompt_version="$(aws_cli bedrock-agent create-prompt-version --prompt-identifier "$prompt_arn" \
  --query version --output text)"

echo "--- release pinned to prompt $prompt_version and guardrail $guardrail_version"
release="$WORK/release/candidate/release.yaml"
uv run --frozen python - "$release" "$prompt_arn" "$prompt_version" "$guardrail_id" "$guardrail_version" <<'PY'
import sys
from pathlib import Path

import yaml

path, arn, prompt_version, guardrail_id, guardrail_version = sys.argv[1:]
data = yaml.safe_load(Path(path).read_text())
data["prompt"].update(arn=arn, version=prompt_version)
data["guardrail"].update(id=guardrail_id, version=guardrail_version)
data["release"]["change"] = "Live test: candidate pinned to the sandbox prompt and guardrail."
Path(path).write_text(yaml.safe_dump(data, sort_keys=False))
PY

cd "$REPO_ROOT"
gate=(uv run --frozen --extra live python -m genai_gate.cli)
echo "--- collect (live)"
"${gate[@]}" collect --live --release "$release" --out "$WORK/run" --region "$REGION"
echo "--- gate"
set +e
"${gate[@]}" evaluate --release "$release" --run "$WORK/run" \
  --baseline-release release/production/release.yaml --baseline-run release/production/run \
  --evidence-dir "$WORK/evidence" --title "live test $RUN_ID"
verdict=$?
set -e
if [ "$verdict" -gt 1 ]; then
  echo "FAIL  the live run produced invalid or incomplete evidence" >&2
  exit 1
fi
echo "gate verdict exit code: $verdict (0 PASS, 1 BLOCK; live scores differ from the recorded fixtures)"

echo "--- promote, promote again, roll back"
scripts/promote.sh staging release/production/release.yaml
first="$(aws_cli ssm get-parameter --name "/$NAME/staging/release" --with-decryption --query Parameter.Value --output text)"
scripts/promote.sh staging "$release"
scripts/rollback.sh staging
after="$(aws_cli ssm get-parameter --name "/$NAME/staging/release" --with-decryption --query Parameter.Value --output text)"
if [ "$first" != "$after" ]; then
  echo "FAIL  rollback did not restore the previous serving configuration" >&2
  exit 1
fi
echo "PASS  live test: apply, collect, gate, promote, rollback"
