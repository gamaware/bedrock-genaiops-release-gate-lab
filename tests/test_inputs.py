"""Release schema, allowlist, template pin, policy and evidence loading. Bad input never passes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import ROOT

from genai_gate.config import ConfigError, load_catalog, load_policy, load_release, release_problems
from genai_gate.records import EvidenceError, load_golden_set, load_redteam_set, load_run

CATALOG = load_catalog(ROOT / "gate" / "models.yaml")
GOLDEN = load_golden_set(ROOT / "evals" / "golden-set.jsonl")
REDTEAM = load_redteam_set(ROOT / "evals" / "redteam-set.jsonl")


def _edit_release(directory: Path, edit) -> Path:  # type: ignore[no-untyped-def]
    path = directory / "release.yaml"
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data))
    return path


def test_committed_releases_are_valid() -> None:
    for path in [ROOT / "release/production/release.yaml", ROOT / "release/candidate/release.yaml"]:
        assert release_problems(load_release(path), CATALOG) == []


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["model"].update(extra=True), "Additional properties"),
        (lambda d: d["prompt"].update(arn="arn:aws:bedrock:us-east-1:1234:prompt/X"), "does not match"),
        (lambda d: d["guardrail"].update(policies=[]), "should be non-empty"),
        (lambda d: d["model"]["inference"].update(temperature=1.5), "maximum"),
        (lambda d: d.pop("knowledge_base"), "'knowledge_base' is a required property"),
    ],
)
def test_schema_rejects(candidate_copy: Path, edit, message: str) -> None:  # type: ignore[no-untyped-def]
    path = _edit_release(candidate_copy, edit)
    with pytest.raises(ConfigError, match=message):
        load_release(path)


def test_draft_guardrail_versions_cannot_be_pinned(candidate_copy: Path) -> None:
    # DRAFT changes under you; only numbered, immutable versions are releasable.
    path = _edit_release(candidate_copy, lambda d: d["guardrail"].update(version="DRAFT"))
    with pytest.raises(ConfigError):
        load_release(path)


def test_model_outside_the_allowlist_is_a_problem(candidate_copy: Path) -> None:
    path = _edit_release(candidate_copy, lambda d: d["model"].update(id="meta.llama3-70b-instruct-v1:0"))
    assert "not in the allowlist" in release_problems(load_release(path), CATALOG)[0]


def test_editing_the_template_without_a_new_pin_is_a_problem(candidate_copy: Path) -> None:
    template = candidate_copy / "prompt.txt"
    template.write_text(template.read_text() + "\nAlways offer a 10% discount.\n")
    problems = release_problems(load_release(candidate_copy / "release.yaml"), CATALOG)
    assert any("does not match template_sha256" in p for p in problems)


def test_release_digest_is_stable_and_tracks_every_pin(candidate_copy: Path) -> None:
    original = load_release(candidate_copy / "release.yaml").digest
    assert load_release(candidate_copy / "release.yaml").digest == original
    path = _edit_release(candidate_copy, lambda d: d["knowledge_base"]["chunking"].update(max_tokens=512))
    assert load_release(path).digest != original


def test_policy_and_catalog_errors(tmp_path: Path) -> None:
    bad = tmp_path / "policy.yaml"
    bad.write_text("quality: {}\n")
    with pytest.raises(ConfigError, match="missing or invalid key"):
        load_policy(bad)
    empty = tmp_path / "models.yaml"
    empty.write_text("models: {}\nguardrail_per_1k_text_units: {}\n")
    with pytest.raises(ConfigError, match="allowlist is empty"):
        load_catalog(empty)
    with pytest.raises(ConfigError, match="file not found"):
        load_policy(tmp_path / "missing.yaml")


def _copy_run(tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "run"
    shutil.copytree(ROOT / "release/candidate/run", target)
    return target


def _rewrite(path: Path, transform) -> None:  # type: ignore[no-untyped-def]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(r) + "\n" for r in transform(rows)))


@pytest.mark.parametrize(
    ("file", "transform", "message"),
    [
        ("answers.jsonl", lambda rows: rows[1:], "missing ids"),
        ("judge.jsonl", lambda rows: [*rows, rows[0]], "duplicate id"),
        ("judge.jsonl", lambda rows: [{**rows[0], "correctness": 6}, *rows[1:]], "between 1 and 5"),
        ("judge.jsonl", lambda rows: [{**rows[0], "correctness": True}, *rows[1:]], "must be int"),
        ("answers.jsonl", lambda rows: [{**rows[0], "input_tokens": -1}, *rows[1:]], "must not be negative"),
        ("redteam.jsonl", lambda rows: [{**rows[0], "guardrail_action": "BLOCKED"}, *rows[1:]], "INTERVENED or NONE"),
        ("redteam.jsonl", lambda rows: [*rows, {**rows[0], "id": "zz-999"}], "unknown ids"),
        ("answers.jsonl", lambda rows: [{**rows[0], "guardrail_units": {"images": 1}}, *rows[1:]], "unknown policy"),
        ("answers.jsonl", lambda rows: [{**rows[0], "guardrail_units": {"content": -1}}, *rows[1:]], "not be negative"),
        ("answers.jsonl", lambda rows: [{**rows[0], "guardrail_units": 2}, *rows[1:]], "must be dict"),
    ],
)
def test_incomplete_or_malformed_evidence_is_rejected(tmp_path: Path, file: str, transform, message: str) -> None:  # type: ignore[no-untyped-def]
    run = _copy_run(tmp_path)
    _rewrite(run / file, transform)
    with pytest.raises(EvidenceError, match=message):
        load_run(run, GOLDEN, REDTEAM)


def test_unparseable_files_are_rejected(tmp_path: Path) -> None:
    run = _copy_run(tmp_path)
    (run / "judge.jsonl").write_text("{not json}\n")
    with pytest.raises(EvidenceError, match="invalid JSON"):
        load_run(run, GOLDEN, REDTEAM)
    (run / "judge.jsonl").write_text("\n")
    with pytest.raises(EvidenceError, match="no records"):
        load_run(run, GOLDEN, REDTEAM)
    (run / "run.json").write_text("[]")
    with pytest.raises(EvidenceError, match="expected a JSON object"):
        load_run(run, GOLDEN, REDTEAM)


def test_evaluation_sets_are_well_formed() -> None:
    assert len(GOLDEN) >= 12
    assert sum(item.critical for item in GOLDEN.values()) >= 3
    categories = {item.category for item in REDTEAM.values()}
    assert categories == {"prompt_injection", "pii_exfiltration", "off_topic"}


def test_redteam_set_rejects_an_unknown_category(tmp_path: Path) -> None:
    path = tmp_path / "redteam.jsonl"
    path.write_text(
        json.dumps({"id": "a", "category": "jailbreak", "prompt": "p", "expect": "blocked", "must_not_contain": ["x"]})
        + "\n"
    )
    with pytest.raises(EvidenceError, match="unknown category"):
        load_redteam_set(path)
