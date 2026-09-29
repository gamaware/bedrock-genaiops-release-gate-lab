"""Shared fixtures. Every test runs offline against files in this repository."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from genai_gate.config import load_catalog, load_policy, load_release
from genai_gate.gate import GateInputs, load_inputs

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = sorted(p.name for p in (ROOT / "fixtures" / "scenarios").iterdir() if p.is_dir())


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # The CLI's default paths (gate/, evals/) are relative to the repository root.
    monkeypatch.chdir(ROOT)


def _relative(path: Path) -> Path:
    # Findings quote paths; relative ones keep evidence identical on every machine.
    return path.relative_to(ROOT) if path.is_absolute() else path


def gate_inputs(release_dir: Path, baseline_dir: Path = ROOT / "release" / "production") -> GateInputs:
    release_dir, baseline_dir = _relative(release_dir), _relative(baseline_dir)
    return load_inputs(
        release=load_release(release_dir / "release.yaml"),
        run_dir=release_dir / "run",
        baseline_release=load_release(baseline_dir / "release.yaml"),
        baseline_dir=baseline_dir / "run",
        golden_path=ROOT / "evals" / "golden-set.jsonl",
        redteam_path=ROOT / "evals" / "redteam-set.jsonl",
        catalog=load_catalog(ROOT / "gate" / "models.yaml"),
        policy=load_policy(ROOT / "gate" / "policy.yaml"),
    )


@pytest.fixture
def candidate_copy(tmp_path: Path) -> Path:
    """A writable copy of the release candidate, for tests that tamper with it."""
    target = tmp_path / "candidate"
    shutil.copytree(ROOT / "release" / "candidate", target)
    return target
