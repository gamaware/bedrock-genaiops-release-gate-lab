"""Evaluation sets and recorded runs, loaded from JSON Lines.

A run directory holds everything one release produced against the evaluation
sets, so the gate can score it with no model call:

    run.json        manifest: digests of the release and of both sets
    answers.jsonl   one answer per golden question: tokens, end-to-end latency
                    (guardrail and model calls) and guardrail units per policy
    judge.jsonl     one rubric score per golden question (LLM-as-judge output)
    redteam.jsonl   one outcome per red-team prompt (guardrail action, output)

Any gap (a missing answer, an unknown id, a score out of range) raises
EvidenceError: incomplete evidence blocks a release, it never passes one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

METRICS = ("correctness", "faithfulness", "completeness")
REDTEAM_CATEGORIES = ("prompt_injection", "pii_exfiltration", "off_topic")
# Guardrail policies as named in gate/models.yaml and release.yaml.
GUARDRAIL_POLICIES = ("content", "denied_topics", "sensitive_information", "word", "contextual_grounding")


class EvidenceError(ValueError):
    """The evaluation sets or a recorded run are missing, malformed or inconsistent."""


@dataclass(frozen=True)
class GoldenItem:
    id: str
    question: str
    context: str
    reference: str
    critical: bool


@dataclass(frozen=True)
class RedTeamItem:
    id: str
    category: str
    prompt: str
    context: str
    expect: Literal["blocked", "refused"]
    must_not_contain: tuple[str, ...]


@dataclass(frozen=True)
class Answer:
    id: str
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    # Billed guardrail text units per policy, from the ApplyGuardrail usage field.
    guardrail_units: dict[str, int]


@dataclass(frozen=True)
class JudgeScore:
    id: str
    correctness: int
    faithfulness: int
    completeness: int
    rationale: str

    def metric(self, name: str) -> int:
        return int(getattr(self, name))


@dataclass(frozen=True)
class RedTeamOutcome:
    id: str
    guardrail_action: Literal["INTERVENED", "NONE"]
    output: str


@dataclass(frozen=True)
class Manifest:
    release_digest: str
    golden_set_digest: str
    redteam_set_digest: str
    source: str


@dataclass(frozen=True)
class Run:
    path: Path
    manifest: Manifest
    answers: dict[str, Answer]
    judge: dict[str, JudgeScore]
    redteam: dict[str, RedTeamOutcome]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvidenceError(f"{path}: file not found")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"{path}:{number}: invalid JSON ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise EvidenceError(f"{path}:{number}: expected a JSON object")
        rows.append(row)
    if not rows:
        raise EvidenceError(f"{path}: no records")
    return rows


def _field(row: dict[str, Any], key: str, kind: type, where: str) -> Any:
    value = row.get(key)
    # bool is an int subclass; never accept it where a number is expected.
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise EvidenceError(f"{where}: field '{key}' must be {kind.__name__}")
    return value


def _index[T](items: list[T], path: Path) -> dict[str, T]:
    indexed: dict[str, T] = {}
    for item in items:
        item_id = item.id  # type: ignore[attr-defined]
        if item_id in indexed:
            raise EvidenceError(f"{path}: duplicate id {item_id}")
        indexed[item_id] = item
    return indexed


def load_golden_set(path: Path) -> dict[str, GoldenItem]:
    items = []
    for row in read_jsonl(path):
        where = f"{path} id={row.get('id')}"
        items.append(
            GoldenItem(
                id=_field(row, "id", str, where),
                question=_field(row, "question", str, where),
                context=_field(row, "context", str, where),
                reference=_field(row, "reference", str, where),
                critical=_field(row, "critical", bool, where),
            )
        )
    return _index(items, path)


def load_redteam_set(path: Path) -> dict[str, RedTeamItem]:
    items = []
    for row in read_jsonl(path):
        where = f"{path} id={row.get('id')}"
        category = _field(row, "category", str, where)
        if category not in REDTEAM_CATEGORIES:
            raise EvidenceError(f"{where}: unknown category {category}")
        expect = _field(row, "expect", str, where)
        if expect not in ("blocked", "refused"):
            raise EvidenceError(f"{where}: expect must be 'blocked' or 'refused'")
        forbidden = _field(row, "must_not_contain", list, where)
        if not forbidden or not all(isinstance(text, str) and text for text in forbidden):
            raise EvidenceError(f"{where}: must_not_contain needs at least one non-empty string")
        items.append(
            RedTeamItem(
                id=_field(row, "id", str, where),
                category=category,
                prompt=_field(row, "prompt", str, where),
                context=str(row.get("context", "")),
                expect=expect,
                must_not_contain=tuple(forbidden),
            )
        )
    return _index(items, path)


def _score(row: dict[str, Any], key: str, where: str) -> int:
    value = _field(row, key, int, where)
    if not 1 <= value <= 5:
        raise EvidenceError(f"{where}: {key} must be between 1 and 5")
    return value


def _count(row: dict[str, Any], key: str, where: str) -> int:
    value = _field(row, key, int, where)
    if value < 0:
        raise EvidenceError(f"{where}: {key} must not be negative")
    return value


def _policy_units(row: dict[str, Any], where: str) -> dict[str, int]:
    units = _field(row, "guardrail_units", dict, where)
    for policy in units:
        if policy not in GUARDRAIL_POLICIES:
            raise EvidenceError(f"{where}: guardrail_units has unknown policy {policy}")
    return {policy: _count(units, policy, f"{where} guardrail_units") for policy in units}


def load_run(path: Path, golden: dict[str, GoldenItem], redteam: dict[str, RedTeamItem]) -> Run:
    """Load a run and check it covers exactly the given evaluation sets."""
    manifest_path = path / "run.json"
    if not manifest_path.is_file():
        raise EvidenceError(f"{manifest_path}: file not found")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{manifest_path}: invalid JSON ({exc.msg})") from exc
    if not isinstance(raw, dict):
        raise EvidenceError(f"{manifest_path}: expected a JSON object")
    manifest = Manifest(
        release_digest=_field(raw, "release_digest", str, str(manifest_path)),
        golden_set_digest=_field(raw, "golden_set_digest", str, str(manifest_path)),
        redteam_set_digest=_field(raw, "redteam_set_digest", str, str(manifest_path)),
        source=_field(raw, "source", str, str(manifest_path)),
    )

    answers_path = path / "answers.jsonl"
    answers = _index(
        [
            Answer(
                id=_field(row, "id", str, str(answers_path)),
                text=_field(row, "answer", str, f"{answers_path} id={row.get('id')}"),
                input_tokens=_count(row, "input_tokens", f"{answers_path} id={row.get('id')}"),
                output_tokens=_count(row, "output_tokens", f"{answers_path} id={row.get('id')}"),
                latency_ms=_count(row, "latency_ms", f"{answers_path} id={row.get('id')}"),
                guardrail_units=_policy_units(row, f"{answers_path} id={row.get('id')}"),
            )
            for row in read_jsonl(answers_path)
        ],
        answers_path,
    )

    judge_path = path / "judge.jsonl"
    judge = _index(
        [
            JudgeScore(
                id=_field(row, "id", str, str(judge_path)),
                correctness=_score(row, "correctness", f"{judge_path} id={row.get('id')}"),
                faithfulness=_score(row, "faithfulness", f"{judge_path} id={row.get('id')}"),
                completeness=_score(row, "completeness", f"{judge_path} id={row.get('id')}"),
                rationale=_field(row, "rationale", str, f"{judge_path} id={row.get('id')}"),
            )
            for row in read_jsonl(judge_path)
        ],
        judge_path,
    )

    redteam_path = path / "redteam.jsonl"
    outcomes = []
    for row in read_jsonl(redteam_path):
        where = f"{redteam_path} id={row.get('id')}"
        action = _field(row, "guardrail_action", str, where)
        if action not in ("INTERVENED", "NONE"):
            raise EvidenceError(f"{where}: guardrail_action must be INTERVENED or NONE")
        outcomes.append(
            RedTeamOutcome(
                id=_field(row, "id", str, where), guardrail_action=action, output=_field(row, "output", str, where)
            )
        )
    redteam_outcomes = _index(outcomes, redteam_path)

    for name, expected, actual in (
        ("answers.jsonl", golden, answers),
        ("judge.jsonl", golden, judge),
        ("redteam.jsonl", redteam, redteam_outcomes),
    ):
        missing = sorted(set(expected) - set(actual))
        unknown = sorted(set(actual) - set(expected))
        if missing or unknown:
            raise EvidenceError(f"{path / name}: missing ids {missing or '[]'}, unknown ids {unknown or '[]'}")

    return Run(path=path, manifest=manifest, answers=answers, judge=judge, redteam=redteam_outcomes)
