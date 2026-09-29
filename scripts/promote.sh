#!/usr/bin/env bash
# Promote a release that passed the gate to an alias (staging or prod):
# write its serving configuration to the alias's SSM parameter and label the
# new parameter version with the release digest, so history shows which
# release each version was.
#
#   scripts/promote.sh <staging|prod> <release.yaml>
#
# Env: GENAI_NAME (default harbor-support, the Terraform `name`),
#      AWS_REGION. Credentials come from the caller (OIDC role in CI).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

alias_name="${1:?usage: promote.sh <staging|prod> <release.yaml>}"
release_file="${2:?usage: promote.sh <staging|prod> <release.yaml>}"
case "$alias_name" in
  staging | prod) ;;
  *)
    echo "alias must be staging or prod" >&2
    exit 2
    ;;
esac

parameter="/${GENAI_NAME:-harbor-support}/$alias_name/release"
value="$(uv run --project "$repo_root" --frozen python -m genai_gate.cli serving-config --release "$release_file")"
digest="$(jq -r .release_digest <<< "$value")"

version="$(aws ssm put-parameter --name "$parameter" --type SecureString --overwrite \
  --value "$value" --query Version --output text)"
# Labels start with a letter and may not start with "aws" or "ssm".
aws ssm label-parameter-version --name "$parameter" --parameter-version "$version" \
  --labels "r-${digest:0:12}" > /dev/null

echo "promoted release ${digest:0:12} to $parameter (version $version)"
