#!/usr/bin/env bash
# Roll an alias back to the serving configuration it had before the last
# promotion: read the parameter history, write the previous value as a new
# version and label it. Nothing is deleted, so the rollback is itself
# auditable and can be rolled forward the same way.
#
#   scripts/rollback.sh <staging|prod>
#
# Env: GENAI_NAME (default harbor-support), AWS_REGION.
set -euo pipefail

alias_name="${1:?usage: rollback.sh <staging|prod>}"
case "$alias_name" in
  staging | prod) ;;
  *)
    echo "alias must be staging or prod" >&2
    exit 2
    ;;
esac
parameter="/${GENAI_NAME:-harbor-support}/$alias_name/release"

history="$(aws ssm get-parameter-history --name "$parameter" --with-decryption --output json)"
count="$(jq '.Parameters | length' <<< "$history")"
if [ "$count" -lt 2 ]; then
  echo "no earlier version of $parameter to roll back to" >&2
  exit 1
fi

current_version="$(jq -r '.Parameters[-1].Version' <<< "$history")"
previous_value="$(jq -r '.Parameters[-2].Value' <<< "$history")"
previous_version="$(jq -r '.Parameters[-2].Version' <<< "$history")"

version="$(aws ssm put-parameter --name "$parameter" --type SecureString --overwrite \
  --value "$previous_value" --query Version --output text)"
aws ssm label-parameter-version --name "$parameter" --parameter-version "$version" \
  --labels "rollback-of-v$current_version" > /dev/null

echo "rolled $parameter back to the value of version $previous_version (now version $version)"
