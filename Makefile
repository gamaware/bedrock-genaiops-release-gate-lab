# One entry point for local and CI runs: the CI verify job calls `make verify`.
# Offline: no AWS credentials and no AWS API calls. The first run downloads
# Python packages, Terraform providers, the tflint AWS ruleset, Semgrep rules
# and the Trivy database.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

UV        ?= uv
TERRAFORM ?= terraform
TFLINT    ?= tflint
CHECKOV   := uvx checkov==3.3.19
RUFF      := uvx ruff@0.16.9
SEMGREP   := uvx semgrep==1.178.0
ACTIONLINT := uvx --from actionlint-py==1.7.12.25 actionlint
ZIZMOR    := uvx zizmor==1.30.1
TF_STACK  := infra/terraform/release-gate
TFLINT_CONFIG := $(CURDIR)/.tflint.hcl
SHELL_FILES := $(wildcard scripts/*.sh)
EVIDENCE_DIR ?= build/evidence

# src/ on the path directly, so runs do not depend on the editable-install .pth file.
export PYTHONPATH := $(CURDIR)/src
GATE := $(UV) run --frozen python -m genai_gate.cli
BASELINE := --baseline-release release/production/release.yaml --baseline-run release/production/run

.PHONY: help verify python test gate scenarios evidence terraform checkov trivy semgrep shell \
	workflows report-check report test-live clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-15s %s\n", $$1, $$2}'

verify: python test gate scenarios terraform checkov trivy semgrep shell workflows report-check ## Run every offline check
	@echo "verify: all checks passed"

python: ## Ruff lint and format check
	$(RUFF) check .
	$(RUFF) format --check .

test: ## pytest: gate rules, loaders, CLI, recorded scenarios, Bedrock adapters through botocore's Stubber
	$(UV) run --frozen pytest

gate: ## The pull request gate: validate and evaluate release/candidate against production
	$(GATE) validate release/candidate/release.yaml
	$(GATE) evaluate --release release/candidate/release.yaml --run release/candidate/run $(BASELINE) \
	  --evidence-dir $(EVIDENCE_DIR) --title "support-answer candidate" > /dev/null
	@echo "pass  release/candidate: $$(jq -r .verdict $(EVIDENCE_DIR)/evidence.json), evidence in $(EVIDENCE_DIR)"

scenarios: ## Every recorded scenario gets its expected verdict through the CLI exit code
	scripts/run-scenarios.sh

evidence: ## Rewrite report/evidence/ from the scenarios (review the diff before committing)
	@for dir in fixtures/scenarios/*/; do \
	  name="$$(basename "$$dir")"; \
	  $(GATE) evaluate --release "$$dir/release.yaml" --run "$$dir/run" $(BASELINE) --title "$$name" \
	    > "report/evidence/$$name.md" || test $$? -eq 1; \
	done
	@echo "wrote report/evidence/"

terraform: ## fmt check, validate, tflint and mocked terraform test
	$(TERRAFORM) fmt -check -recursive infra/terraform
	$(TERRAFORM) -chdir=$(TF_STACK) init -backend=false -input=false > /dev/null
	$(TERRAFORM) -chdir=$(TF_STACK) validate
	cd $(TF_STACK) && $(TFLINT) --init --config=$(TFLINT_CONFIG) > /dev/null && $(TFLINT) --config=$(TFLINT_CONFIG)
	$(TERRAFORM) -chdir=$(TF_STACK) test

checkov: ## Policy checks on Terraform and the workflows (.checkov.yaml)
	$(CHECKOV) --config-file .checkov.yaml

trivy: ## Trivy misconfiguration and secret scan of the repository
	trivy fs --quiet --scanners misconfig,secret --exit-code 1 --severity HIGH,CRITICAL \
	  --skip-dirs '**/.terraform' --skip-dirs .venv .

semgrep: ## Semgrep rulesets for Python, Terraform, workflows and secrets (rules download from the registry)
	$(SEMGREP) scan --metrics=off --error --quiet \
	  --config p/python --config p/terraform --config p/github-actions --config p/secrets

shell: ## shellcheck and shellharden on every script
	shellcheck --severity=style $(SHELL_FILES)
	shellharden --check $(SHELL_FILES)

workflows: ## actionlint and zizmor on the workflows
	$(ACTIONLINT)
	$(ZIZMOR) --offline --config zizmor.yml .github/workflows

report-check: ## report/REPORT.pdf was built from the current report/REPORT.md
	@shasum -a 256 --check --status report/REPORT.sha256 \
	  || { echo "FAIL  report/REPORT.pdf is out of date: run make report and commit it"; exit 1; }
	@echo "pass  report/REPORT.pdf matches report/REPORT.md"

report: ## Rebuild report/REPORT.pdf with the pinned pandoc/latex image (needs Docker)
	scripts/build-report.sh

test-live: ## Manual: apply, collect a live run, gate, promote, roll back, destroy (personal sandbox only)
	scripts/test-live.sh

clean: ## Remove gate output and local caches
	rm -rf build .pytest_cache .ruff_cache $(TF_STACK)/.terraform
