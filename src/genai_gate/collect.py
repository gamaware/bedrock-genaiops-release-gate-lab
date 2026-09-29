"""Produce a run directory by sending the evaluation sets through the serving path.

The serving path is the one production uses: the pinned managed prompt
version, context retrieved from the pinned knowledge base, guardrail on the
input, the pinned model, guardrail on the output with the retrieved context as
its grounding source. The ports make it testable: the live stage plugs in
Amazon Bedrock clients (live.py), the tests plug in fakes. Scoring happens
later, in gate.py, on the files written here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from genai_gate.config import Release
from genai_gate.records import EvidenceError, GoldenItem, JudgeScore, RedTeamItem


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
    # Billed text units per policy (gate/models.yaml names), from the usage field.
    units: dict[str, int]


class ModelPort(Protocol):
    def answer(self, prompt: str) -> ModelReply: ...


class GuardrailPort(Protocol):
    def check(
        self,
        text: str,
        source: Literal["INPUT", "OUTPUT"],
        *,
        grounding_source: str | None = None,
        query: str | None = None,
    ) -> GuardrailReply: ...


class JudgePort(Protocol):
    def score(self, item: GoldenItem, answer: str) -> JudgeScore: ...


class PromptPort(Protocol):
    def template(self) -> str:
        """The template text of the pinned managed prompt version."""
        ...


class RetrieverPort(Protocol):
    def retrieve(self, question: str) -> str:
        """Context retrieved from the pinned knowledge base for one question."""
        ...


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
    units: dict[str, int]
    # End to end: both guardrail calls and the model call, as a customer waits for them.
    latency_ms: int


def _add(*parts: dict[str, int]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for part in parts:
        total.update(part)
    return dict(total)


def serve(
    template: str,
    question: str,
    context: str,
    model: ModelPort,
    guardrail: GuardrailPort,
    clock: Callable[[], float] = time.perf_counter,
) -> Served:
    start = clock()
    screened = guardrail.check(question, "INPUT")
    if screened.intervened:
        return Served(screened.text, True, None, _add(screened.units), round((clock() - start) * 1000))
    reply = model.answer(render(template, question=question, context=context))
    # Contextual grounding needs the source the answer must stay faithful to and the question it answers.
    checked = guardrail.check(reply.text, "OUTPUT", grounding_source=context or None, query=question)
    return Served(
        checked.text,
        checked.intervened,
        reply,
        _add(screened.units, checked.units),
        round((clock() - start) * 1000),
    )


def pinned_template(release: Release, prompt: PromptPort) -> str:
    """Fetch the pinned prompt version and check it is the template the release was reviewed with."""
    template = prompt.template()
    digest = hashlib.sha256(template.encode("utf-8")).hexdigest()
    expected = release.data["prompt"]["template_sha256"]
    if digest != expected:
        raise EvidenceError(
            f"prompt {release.data['prompt']['arn']} version {release.data['prompt']['version']} has template "
            f"{digest[:12]}, but the release pins {expected[:12]}"
        )
    return template


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def collect(
    *,
    release: Release,
    golden: dict[str, GoldenItem],
    redteam: dict[str, RedTeamItem],
    set_digests: tuple[str, str],
    prompt: PromptPort,
    retriever: RetrieverPort,
    model: ModelPort,
    guardrail: GuardrailPort,
    judge: JudgePort,
    out_dir: Path,
    source: str,
    clock: Callable[[], float] = time.perf_counter,
) -> None:
    template = pinned_template(release, prompt)
    answers, scores, outcomes = [], [], []
    for item in golden.values():
        # Golden questions run on what the knowledge base returns, so a broken or re-chunked KB shows in the scores.
        context = retriever.retrieve(item.question)
        if not context.strip():
            raise EvidenceError(f"the knowledge base returned no context for {item.id}")
        served = serve(template, item.question, context, model, guardrail, clock)
        reply = served.reply or ModelReply(served.text, 0, 0, 0)
        answers.append(
            {
                "id": item.id,
                "answer": served.text,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "latency_ms": served.latency_ms,
                "guardrail_units": served.units,
            }
        )
        score = judge.score(dataclasses.replace(item, context=context), served.text)
        scores.append(
            {
                "id": item.id,
                "correctness": score.correctness,
                "faithfulness": score.faithfulness,
                "completeness": score.completeness,
                "rationale": score.rationale,
            }
        )
    # Red-team prompts keep their planted context: it carries the indirect injections under test.
    for item in redteam.values():
        served = serve(template, item.prompt, item.context, model, guardrail, clock)
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
