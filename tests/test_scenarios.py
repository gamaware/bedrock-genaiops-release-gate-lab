"""End to end: every recorded scenario gets the verdict it expects, with no model call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT, SCENARIOS, gate_inputs

from genai_gate.cli import EXIT_BLOCK, EXIT_PASS, main
from genai_gate.evidence import to_markdown
from genai_gate.gate import evaluate


def test_there_is_a_passing_and_several_blocking_scenarios() -> None:
    verdicts = [
        json.loads((ROOT / "fixtures/scenarios" / s / "expected.json").read_text())["verdict"] for s in SCENARIOS
    ]
    assert verdicts.count("PASS") == 1
    assert verdicts.count("BLOCK") >= 5


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_verdict(scenario: str) -> None:
    directory = ROOT / "fixtures" / "scenarios" / scenario
    expected = json.loads((directory / "expected.json").read_text())
    decision = evaluate(gate_inputs(directory))
    assert decision.verdict == expected["verdict"]
    assert decision.failed_checks == expected["failed_checks"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_through_the_cli(scenario: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = Path("fixtures/scenarios") / scenario
    expected = json.loads((directory / "expected.json").read_text())
    code = main(
        [
            "evaluate",
            "--release",
            str(directory / "release.yaml"),
            "--run",
            str(directory / "run"),
            "--baseline-release",
            "release/production/release.yaml",
            "--baseline-run",
            "release/production/run",
            "--evidence-dir",
            str(tmp_path),
            "--title",
            scenario,
        ]
    )
    assert code == (EXIT_PASS if expected["verdict"] == "PASS" else EXIT_BLOCK)
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["verdict"] == expected["verdict"]
    assert f"**Verdict: {expected['verdict']}.**" in capsys.readouterr().out


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_committed_evidence_is_current(scenario: str) -> None:
    """report/evidence/ is what `make evidence` writes; a policy or fixture change must regenerate it."""
    decision = evaluate(gate_inputs(ROOT / "fixtures" / "scenarios" / scenario))
    committed = ROOT / "report" / "evidence" / f"{scenario}.md"
    assert committed.read_text() == to_markdown(decision, scenario), f"run `make evidence` and commit {committed}"


def test_the_release_candidate_in_this_repo_passes() -> None:
    decision = evaluate(gate_inputs(ROOT / "release" / "candidate"))
    assert decision.verdict == "PASS", decision.checks
    assert [pin for pin, _, _ in decision.changes] == ["prompt", "prompt template"]


def test_blocking_scenarios_explain_themselves() -> None:
    loosened = evaluate(gate_inputs(ROOT / "fixtures/scenarios/guardrail-loosened-redteam"))
    findings = next(c for c in loosened.checks if c.name == "red team").findings
    assert any("regression on pii-001" in f and "555-0142" in f for f in findings)
    assert any("regression on pii-004" in f for f in findings)

    swap = evaluate(gate_inputs(ROOT / "fixtures/scenarios/model-swap-quality-regression"))
    quality = next(c for c in swap.checks if c.name == "quality").findings
    assert any("critical question gs-008" in f for f in quality)

    stale = evaluate(gate_inputs(ROOT / "fixtures/scenarios/stale-evidence"))
    release = next(c for c in stale.checks if c.name == "release").findings
    assert any("stale evidence" in f for f in release)
