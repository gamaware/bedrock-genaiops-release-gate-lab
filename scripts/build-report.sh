#!/usr/bin/env bash
# Build report/REPORT.pdf from report/REPORT.md with pandoc and xelatex, in the
# same pinned pandoc/latex image and with the same arguments as the shared
# gamaware/.github report workflow that CI calls. REPORT.md is the
# deliverable; the PDF is generated from it and never edited by hand.
# Relative links become links to the repository on GitHub, so they still work
# when the PDF travels on its own. report/REPORT.sha256 records both hashes,
# so `make report-check` can verify the pair offline without Docker.
set -euo pipefail

cd "$(dirname "$0")/.."

# Keep in step with PANDOC_IMAGE in gamaware/.github/.github/workflows/report.yml.
image="pandoc/latex:3.11@sha256:cdbf139f607237498b412b3aa051008311d69b88006ab47550efba357af3b277"
repo_url="https://github.com/gamaware/bedrock-genaiops-release-gate-lab/blob/main"
# Also passed as `pandoc-args` to the report job in .github/workflows/ci.yml.
pandoc_args=(
  --pdf-engine=xelatex -V geometry:margin=2.2cm -V papersize=a4 --toc --shift-heading-level-by=-1
)

if ! command -v docker > /dev/null; then
  echo "error: make report needs Docker to run the pinned pandoc/latex image" >&2
  exit 2
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
sed -e "s#](\.\./#](${repo_url}/#g" -e "s#](evidence/#](${repo_url}/report/evidence/#g" \
  report/REPORT.md > "$work/REPORT.md"

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e SOURCE_DATE_EPOCH=0 \
  -v "$work:/data" -w /data "$image" REPORT.md "${pandoc_args[@]}" -o REPORT.pdf
cp "$work/REPORT.pdf" report/REPORT.pdf
shasum -a 256 report/REPORT.md report/REPORT.pdf > report/REPORT.sha256
echo "wrote report/REPORT.pdf and report/REPORT.sha256"
