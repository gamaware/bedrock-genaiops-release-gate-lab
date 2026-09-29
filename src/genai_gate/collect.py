"""Produce a run directory by sending the evaluation sets through the serving path.

The serving path is the one production uses: guardrail on the input, the
pinned model with the pinned prompt, guardrail on the output. The ports make
it testable: the live stage plugs in Amazon Bedrock clients (live.py), the
tests plug in fakes. Scoring happens later, in gate.py, on the files written here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from genai_gate.config import Release
from genai_gate.records import GoldenItem, JudgeScore, RedTeamItem


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class GuardrailReply:
    intervened: bool
    text: str
    text_units: int


class ModelPort(Protocol):
    def answer(self, prompt: str) -> ModelReply: ...


class GuardrailPort(Protocol):
    def check(self, text: str, source: Literal["INPUT", "OUTPUT"]) -> GuardrailReply: ...


class JudgePort(Protocol):
    def score(self, item: GoldenItem, answer: str) -> JudgeScore: ...


def render(template: str, *, question: str, context: str) -> str:
    """Fill the Prompt Management variables {{context}} and {{question}}."""
    if "{{question}}" not in template or "{{context}}" not in template:
        raise ValueError("the prompt template must use both {{context}} and {{question}}")
    return template.replace("{{context}}", context).replace("{{question}}", question)


@dataclass(frozen=True)
class Served:
    text: str
    intervened: bool
    reply: ModelReply | None
    text_units: int


def serve(template: str, question: str, context: str, model: ModelPort, guardrail: GuardrailPort) -> Served:
    screened = guardrail.check(question, "INPUT")
    if screened.intervened:
        return Served(screened.text, True, None, screened.text_units)
    reply = model.answer(render(template, question=question, context=context))
    checked = guardrail.check(reply.text, "OUTPUT")
    return Served(checked.text, checked.intervened, reply, screened.text_units + checked.text_units)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def collect(
    *,
    release: Release,
    golden: dict[str, GoldenItem],
    redteam: dict[str, RedTeamItem],
    set_digests: tuple[str, str],
    model: ModelPort,
    guardrail: GuardrailPort,
    judge: JudgePort,
    out_dir: Path,
    source: str,
) -> None:
    template = release.template_path.read_text(encoding="utf-8")
    answers, scores, outcomes = [], [], []
    for item in golden.values():
        served = serve(template, item.question, item.context, model, guardrail)
        reply = served.reply or ModelReply(served.text, 0, 0, 0)
        answers.append(
            {
                "id": item.id,
                "answer": served.text,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "latency_ms": reply.latency_ms,
                "guardrail_text_units": served.text_units,
            }
        )
        score = judge.score(item, served.text)
        scores.append(
            {
                "id": item.id,
                "correctness": score.correctness,
                "faithfulness": score.faithfulness,
                "completeness": score.completeness,
                "rationale": score.rationale,
            }
        )
    for item in redteam.values():
        served = serve(template, item.prompt, item.context, model, guardrail)
        outcomes.append(
            {"id": item.id, "guardrail_action": "INTERVENED" if served.intervened else "NONE", "output": served.text}
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "release_digest": release.digest,
        "golden_set_digest": set_digests[0],
        "redteam_set_digest": set_digests[1],
        "source": source,
    }
    (out_dir / "run.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(out_dir / "answers.jsonl", answers)
    _write_jsonl(out_dir / "judge.jsonl", scores)
    _write_jsonl(out_dir / "redteam.jsonl", outcomes)
