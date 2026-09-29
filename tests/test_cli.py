"""The command line contract the pipeline relies on: exit codes and outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genai_gate.cli import EXIT_BLOCK, EXIT_INVALID, EXIT_PASS, main


def test_validate_accepts_the_candidate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "release/candidate/release.yaml"]) == EXIT_PASS
    assert "valid (release digest" in capsys.readouterr().out


def test_validate_blocks_a_model_outside_the_allowlist(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "fixtures/scenarios/model-not-allowlisted/release.yaml"]) == EXIT_BLOCK
    assert "not in the allowlist" in capsys.readouterr().err


def test_missing_evidence_is_invalid_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "evaluate",
            "--release",
            "release/candidate/release.yaml",
            "--run",
            str(tmp_path / "nothing-here"),
            "--baseline-release",
            "release/production/release.yaml",
            "--baseline-run",
            "release/production/run",
        ]
    )
    assert code == EXIT_INVALID
    assert "BLOCK (invalid input or incomplete evidence)" in capsys.readouterr().err


def test_collect_refuses_without_the_live_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["collect", "--release", "release/candidate/release.yaml", "--out", "unused"]) == EXIT_INVALID
    assert "--live" in capsys.readouterr().err


def test_serving_config_is_the_value_promoted_through_ssm(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["serving-config", "--release", "release/candidate/release.yaml"]) == EXIT_PASS
    value = json.loads(capsys.readouterr().out)
    assert value["model_id"] == "amazon.nova-lite-v1:0"
    assert value["prompt_version"] == "5"
    assert value["guardrail_version"] == "3"
    assert len(value["release_digest"]) == 64
    # SSM Parameter Store standard tier holds up to 4 KB.
    assert len(json.dumps(value)) < 4096
