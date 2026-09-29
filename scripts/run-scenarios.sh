#!/usr/bin/env bash
# Run the gate CLI on every recorded scenario and compare the exit code with
# the verdict in expected.json: 0 for PASS, 1 for BLOCK. This is the same
# contract the pipeline relies on. Offline; no model or AWS call.
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
gate=(uv run --frozen python -m genai_gate.cli)
status=0

printf '%-32s %-8s %-8s\n' scenario expected actual
for dir in fixtures/scenarios/*/; do
  name="$(basename "$dir")"
  expected="$(jq -r .verdict "$dir/expected.json")"
  set +e
  "${gate[@]}" evaluate \
    --release "$dir/release.yaml" --run "$dir/run" \
    --baseline-release release/production/release.yaml --baseline-run release/production/run > /dev/null
  code=$?
  set -e
  case "$code" in
    0) actual=PASS ;;
    1) actual=BLOCK ;;
    *) actual="ERROR($code)" ;;
  esac
  printf '%-32s %-8s %-8s\n' "$name" "$expected" "$actual"
  if [ "$actual" != "$expected" ]; then
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  echo "FAIL  a scenario did not get its expected verdict" >&2
fi
exit "$status"
