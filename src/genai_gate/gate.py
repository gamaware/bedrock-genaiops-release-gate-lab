"""Run every check and decide: PASS lets the release be promoted, BLOCK stops it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from genai_gate.checks import CheckResult, check_cost, check_quality, check_redteam, check_release
from genai_gate.config import Catalog, Policy, Release
from genai_gate.records import GoldenItem, RedTeamItem, Run, file_digest, load_golden_set, load_redteam_set, load_run


@dataclass(frozen=True)
class GateInputs:
    release: Release
    run: Run
    baseline_release: Release
    baseline_run: Run
    golden: dict[str, GoldenItem]
    redteam: dict[str, RedTeamItem]
    set_digests: tuple[str, str]
    catalog: Catalog
    policy: Policy


@dataclass(frozen=True)
class Decision:
    release_name: str
    change: str
    changes: list[tuple[str, str, str]]
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "BLOCK"

    @property
    def failed_checks(self) -> list[str]:
        return [check.name for check in self.checks if not check.passed]


def load_inputs(
    *,
    release: Release,
    run_dir: Path,
    baseline_release: Release,
    baseline_dir: Path,
    golden_path: Path,
    redteam_path: Path,
    catalog: Catalog,
    policy: Policy,
) -> GateInputs:
    golden = load_golden_set(golden_path)
    redteam = load_redteam_set(redteam_path)
    return GateInputs(
        release=release,
        run=load_run(run_dir, golden, redteam),
        baseline_release=baseline_release,
        baseline_run=load_run(baseline_dir, golden, redteam),
        golden=golden,
        redteam=redteam,
        set_digests=(file_digest(golden_path), file_digest(redteam_path)),
        catalog=catalog,
        policy=policy,
    )


def diff_pins(baseline: Release, candidate: Release) -> list[tuple[str, str, str]]:
    before, after = baseline.pins(), candidate.pins()
    return [(key, before[key], after[key]) for key in before if before[key] != after[key]]


def evaluate(inputs: GateInputs) -> Decision:
    checks = [
        check_release(
            inputs.release, inputs.run, inputs.baseline_release, inputs.baseline_run, inputs.catalog, inputs.set_digests
        ),
        check_quality(inputs.golden, inputs.run, inputs.baseline_run, inputs.policy),
        check_redteam(inputs.redteam, inputs.run, inputs.baseline_run, inputs.policy),
        check_cost(
            inputs.release, inputs.run, inputs.baseline_release, inputs.baseline_run, inputs.catalog, inputs.policy
        ),
    ]
    return Decision(
        release_name=inputs.release.data["release"]["name"],
        change=inputs.release.data["release"]["change"],
        changes=diff_pins(inputs.baseline_release, inputs.release),
        checks=checks,
    )
