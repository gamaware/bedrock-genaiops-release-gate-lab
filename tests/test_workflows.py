"""The workflows' contract with GitHub: environment variables resolve only inside a job that names the environment."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from conftest import ROOT

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
VARS = re.compile(r"vars\.([A-Z_]+)")


def _jobs(path: Path) -> dict[str, dict[str, object]]:
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs", {})


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_job_conditions_do_not_read_variables(path: Path) -> None:
    """Regression: a job-level `if: vars.X != ''` sees only repository variables, so the jobs were always skipped."""
    for name, job in _jobs(path).items():
        assert not VARS.search(str(job.get("if", ""))), f"{path.name}:{name} reads vars in its job condition"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_jobs_that_use_variables_name_an_environment_and_check_them_first(path: Path) -> None:
    for name, job in _jobs(path).items():
        steps = job.get("steps", [])
        used = set(VARS.findall(yaml.safe_dump(steps)))
        if not used:
            continue
        assert job.get("environment"), f"{path.name}:{name} uses {sorted(used)} without an environment"
        first = steps[0]
        checked = set(VARS.findall(yaml.safe_dump(first.get("env", {}))))
        assert checked == used, f"{path.name}:{name} first step must check {sorted(used)}"
        assert "exit 1" in first["run"], f"{path.name}:{name} must fail when a variable is missing"


def test_live_gate_checks_the_baseline_before_recording() -> None:
    steps = _jobs(ROOT / ".github" / "workflows" / "release-gate.yml")["live-gate"]["steps"]
    names = [step["name"] for step in steps]
    assert names.index("Check the baseline is the release prod serves") < names.index("Record a live run")
