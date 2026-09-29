"""The live stage without the network: fake ports for collect, botocore's Stubber for the Bedrock adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.stub import Stubber
from conftest import ROOT

from genai_gate.collect import GuardrailReply, ModelReply, collect, render, serve
from genai_gate.config import Release, load_catalog, load_policy, load_release
from genai_gate.gate import evaluate, load_inputs
from genai_gate.live import BedrockGuardrail, BedrockJudge, BedrockModel, BedrockPrompt, BedrockRetriever, policy_units
from genai_gate.records import EvidenceError, GoldenItem, JudgeScore, file_digest, load_golden_set, load_redteam_set

GOLDEN_PATH = ROOT / "evals" / "golden-set.jsonl"
REDTEAM_PATH = ROOT / "evals" / "redteam-set.jsonl"


class FakeModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def answer(self, prompt: str) -> ModelReply:
        self.prompts.append(prompt)
        return ModelReply("I can't help with that. Please check the policy.", 1500, 200, 900)


UNITS = {"content": 1, "denied_topics": 1, "sensitive_information": 1}


class FakeGuardrail:
    """Blocks inputs that mention stocks; masks a phone number on output."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    def check(
        self, text: str, source: str, *, grounding_source: str | None = None, query: str | None = None
    ) -> GuardrailReply:
        self.calls.append((text, source, grounding_source, query))
        if source == "INPUT" and "stocks" in text:
            return GuardrailReply(True, "Sorry, I can't help with that request.", UNITS)
        units = {**UNITS, "contextual_grounding": 1} if grounding_source else UNITS
        if "555-0142" in text:
            return GuardrailReply(True, text.replace("555-0142", "{PHONE}"), units)
        return GuardrailReply(False, text, units)


class FakeJudge:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def score(self, item: GoldenItem, answer: str) -> JudgeScore:
        self.contexts.append(item.context)
        return JudgeScore(item.id, 5, 5, 4, "fake")


class FakePrompt:
    """The managed prompt version: by default the release's own template."""

    def __init__(self, text: str) -> None:
        self.text = text

    def template(self) -> str:
        return self.text


class FakeRetriever:
    """The knowledge base: returns a marked copy of the golden context, so tests see where context came from."""

    def __init__(self, golden: dict[str, GoldenItem], empty: bool = False) -> None:
        self._by_question = {item.question: item.context for item in golden.values()}
        self._empty = empty
        self.questions: list[str] = []

    def retrieve(self, question: str) -> str:
        self.questions.append(question)
        return "" if self._empty else f"[kb] {self._by_question[question]}"


class Clock:
    """Advances 100 ms on every reading."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.1
        return self.now


def test_render_requires_both_variables() -> None:
    assert render("{{context}} / {{question}}", question="q", context="c") == "c / q"
    with pytest.raises(ValueError, match="both"):
        render("{{question}} only", question="q", context="c")


def test_serve_skips_the_model_when_the_input_is_blocked() -> None:
    model = FakeModel()
    served = serve("{{context}}{{question}}", "Which stocks should I buy?", "", model, FakeGuardrail())
    assert served.intervened and served.reply is None
    assert model.prompts == []


def test_serve_sends_the_context_and_question_to_the_output_guardrail() -> None:
    """Regression: contextual grounding needs a grounding source and a query next to the answer."""
    guardrail = FakeGuardrail()
    served = serve("{{context}}{{question}}", "Return window?", "Returns policy: 30 days.", FakeModel(), guardrail)
    assert guardrail.calls[0] == ("Return window?", "INPUT", None, None)
    assert guardrail.calls[1][1:] == ("OUTPUT", "Returns policy: 30 days.", "Return window?")
    assert served.units == {"content": 2, "denied_topics": 2, "sensitive_information": 2, "contextual_grounding": 1}


def test_serve_latency_covers_the_guardrail_calls() -> None:
    """Regression: latency used to be the Converse latency only, and zero for a blocked input."""

    class SlowGuardrail(FakeGuardrail):
        def __init__(self, clock: Clock) -> None:
            super().__init__()
            self._clock = clock

        def check(self, text: str, source: str, **kwargs: str | None) -> GuardrailReply:
            self._clock.now += 1.0  # each ApplyGuardrail call takes a second
            return super().check(text, source, **kwargs)  # type: ignore[arg-type]

    clock = Clock()
    served = serve("{{context}}{{question}}", "Return window?", "ctx", FakeModel(), SlowGuardrail(clock), clock)
    # Two guardrail calls (2 s) plus the clock's own ticks; the model's reported 900 ms is not what is recorded.
    assert served.latency_ms >= 2000
    clock = Clock()
    blocked = serve("{{context}}{{question}}", "Which stocks?", "", FakeModel(), SlowGuardrail(clock), clock)
    assert blocked.intervened and blocked.latency_ms >= 1000


def _collect(release: Release, out: Path, **overrides: object) -> dict[str, object]:
    golden = load_golden_set(GOLDEN_PATH)
    ports: dict[str, object] = {
        "prompt": FakePrompt(release.template_path.read_text(encoding="utf-8")),
        "retriever": FakeRetriever(golden),
        "model": FakeModel(),
        "guardrail": FakeGuardrail(),
        "judge": FakeJudge(),
        "clock": Clock(),
        **overrides,
    }
    collect(
        release=release,
        golden=golden,
        redteam=load_redteam_set(REDTEAM_PATH),
        set_digests=(file_digest(GOLDEN_PATH), file_digest(REDTEAM_PATH)),
        out_dir=out,
        source="test",
        **ports,  # type: ignore[arg-type]
    )
    return ports


def test_collect_writes_a_run_the_gate_accepts(tmp_path: Path) -> None:
    release = load_release(ROOT / "release" / "candidate" / "release.yaml")
    ports = _collect(release, tmp_path / "run")
    model = ports["model"]
    assert isinstance(model, FakeModel)
    # The pinned template reaches the model with the context and question filled in.
    assert "Internal reference HG-SYS-7731" in model.prompts[0]
    assert "{{question}}" not in model.prompts[0]

    inputs = load_inputs(
        release=release,
        run_dir=tmp_path / "run",
        baseline_release=load_release(ROOT / "release/production/release.yaml"),
        baseline_dir=ROOT / "release/production/run",
        golden_path=GOLDEN_PATH,
        redteam_path=REDTEAM_PATH,
        catalog=load_catalog(ROOT / "gate/models.yaml"),
        policy=load_policy(ROOT / "gate/policy.yaml"),
    )
    decision = evaluate(inputs)
    release_check = next(c for c in decision.checks if c.name == "release")
    assert release_check.passed, release_check.findings
    assert inputs.run.redteam["ot-001"].guardrail_action == "INTERVENED"
    first = next(iter(inputs.run.answers.values()))
    assert first.guardrail_units["contextual_grounding"] == 1
    assert first.latency_ms > 0


def test_collect_answers_golden_questions_from_the_knowledge_base(tmp_path: Path) -> None:
    """Regression: the live run used the fixture context instead of querying the pinned knowledge base."""
    release = load_release(ROOT / "release" / "candidate" / "release.yaml")
    ports = _collect(release, tmp_path / "run")
    retriever, model, judge = ports["retriever"], ports["model"], ports["judge"]
    assert isinstance(retriever, FakeRetriever) and isinstance(model, FakeModel) and isinstance(judge, FakeJudge)
    golden = load_golden_set(GOLDEN_PATH)
    assert retriever.questions == [item.question for item in golden.values()]
    assert "[kb] " in model.prompts[0]
    assert all(context.startswith("[kb] ") for context in judge.contexts)


def test_collect_fails_when_the_knowledge_base_returns_nothing(tmp_path: Path) -> None:
    release = load_release(ROOT / "release" / "candidate" / "release.yaml")
    with pytest.raises(EvidenceError, match="no context"):
        _collect(release, tmp_path / "run", retriever=FakeRetriever(load_golden_set(GOLDEN_PATH), empty=True))
    assert not (tmp_path / "run").exists()


def test_collect_uses_the_managed_prompt_version_and_checks_its_hash(tmp_path: Path) -> None:
    """Regression: the live run read the local prompt file, so a missing or different prompt version could pass."""
    release = load_release(ROOT / "release" / "candidate" / "release.yaml")
    with pytest.raises(EvidenceError, match="but the release pins"):
        _collect(release, tmp_path / "run", prompt=FakePrompt("{{context}} a different prompt {{question}}"))
    assert not (tmp_path / "run").exists()


@pytest.fixture
def runtime() -> tuple[object, Stubber]:
    # Unsigned: the Stubber answers every call, so no credentials are needed or read.
    client = boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def _converse_response(text: str) -> dict[str, object]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1200, "outputTokens": 150, "totalTokens": 1350},
        "metrics": {"latencyMs": 830},
    }


def test_bedrock_model_calls_converse_with_the_pinned_settings(runtime: tuple[object, Stubber]) -> None:
    client, stubber = runtime
    stubber.add_response(
        "converse",
        _converse_response("Unopened items: 30 days."),
        {
            "modelId": "amazon.nova-lite-v1:0",
            "messages": [{"role": "user", "content": [{"text": "prompt"}]}],
            "inferenceConfig": {"maxTokens": 400, "temperature": 0.2, "topP": 0.9},
        },
    )
    reply = BedrockModel(client, "amazon.nova-lite-v1:0", {"max_tokens": 400, "temperature": 0.2, "top_p": 0.9}).answer(
        "prompt"
    )
    assert reply == ModelReply("Unopened items: 30 days.", 1200, 150, 830)


def test_bedrock_guardrail_reads_action_output_and_units(runtime: tuple[object, Stubber]) -> None:
    client, stubber = runtime
    stubber.add_response(
        "apply_guardrail",
        {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "The phone is {PHONE}."}],
            "assessments": [],
            "usage": {
                "topicPolicyUnits": 1,
                "contentPolicyUnits": 1,
                "wordPolicyUnits": 0,
                "sensitiveInformationPolicyUnits": 1,
                "sensitiveInformationPolicyFreeUnits": 0,
                "contextualGroundingPolicyUnits": 0,
            },
        },
        {
            "guardrailIdentifier": "hg7k2m9q4x1a",
            "guardrailVersion": "3",
            "source": "OUTPUT",
            "content": [{"text": {"text": "The phone is 555-0142."}}],
        },
    )
    stubber.add_response(
        "apply_guardrail",
        {
            "action": "NONE",
            "outputs": [],
            "assessments": [],
            "usage": {
                "topicPolicyUnits": 2,
                "contentPolicyUnits": 2,
                "wordPolicyUnits": 0,
                "sensitiveInformationPolicyUnits": 2,
                "sensitiveInformationPolicyFreeUnits": 0,
                "contextualGroundingPolicyUnits": 0,
            },
        },
    )
    guardrail = BedrockGuardrail(client, "hg7k2m9q4x1a", "3")
    assert guardrail.check("The phone is 555-0142.", "OUTPUT") == GuardrailReply(
        True, "The phone is {PHONE}.", {"denied_topics": 1, "content": 1, "sensitive_information": 1}
    )
    assert guardrail.check("Plain text", "INPUT") == GuardrailReply(
        False, "Plain text", {"denied_topics": 2, "content": 2, "sensitive_information": 2}
    )


def test_bedrock_guardrail_qualifies_the_grounding_source_and_query(runtime: tuple[object, Stubber]) -> None:
    """Regression: the output check sent unqualified text, so contextual grounding never ran."""
    client, stubber = runtime
    stubber.add_response(
        "apply_guardrail",
        {
            "action": "NONE",
            "outputs": [],
            "assessments": [],
            "usage": {
                "topicPolicyUnits": 1,
                "contentPolicyUnits": 1,
                "wordPolicyUnits": 0,
                "sensitiveInformationPolicyUnits": 1,
                "sensitiveInformationPolicyFreeUnits": 0,
                "contextualGroundingPolicyUnits": 1,
            },
        },
        {
            "guardrailIdentifier": "hg7k2m9q4x1a",
            "guardrailVersion": "3",
            "source": "OUTPUT",
            "content": [
                {"text": {"text": "Returns policy: 30 days.", "qualifiers": ["grounding_source"]}},
                {"text": {"text": "Return window?", "qualifiers": ["query"]}},
                {"text": {"text": "30 days.", "qualifiers": ["guard_content"]}},
            ],
        },
    )
    reply = BedrockGuardrail(client, "hg7k2m9q4x1a", "3").check(
        "30 days.", "OUTPUT", grounding_source="Returns policy: 30 days.", query="Return window?"
    )
    assert reply.units["contextual_grounding"] == 1


def test_policy_units_maps_usage_and_refuses_unpriced_billing() -> None:
    usage = {"contentPolicyUnits": 2, "contextualGroundingPolicyUnits": 0, "sensitiveInformationPolicyFreeUnits": 3}
    assert policy_units(usage) == {"content": 2}
    with pytest.raises(EvidenceError, match="does not price"):
        policy_units({"contentPolicyUnits": 1, "automatedReasoningPolicyUnits": 4})


def test_bedrock_judge_parses_a_score(runtime: tuple[object, Stubber]) -> None:
    client, stubber = runtime
    item = load_golden_set(GOLDEN_PATH)["gs-001"]
    reply = 'Here you go: {"correctness": 5, "faithfulness": 4, "completeness": 5, "rationale": "Accurate."}'
    stubber.add_response("converse", _converse_response(reply))
    score = BedrockJudge(client, "amazon.nova-lite-v1:0", "rubric").score(item, "30 days.")
    assert score == JudgeScore("gs-001", 5, 4, 5, "Accurate.")


@pytest.mark.parametrize(
    "reply",
    [
        "I think it is good.",
        '{"correctness": 6, "faithfulness": 4, "completeness": 5}',
        '{"correctness": "5", "faithfulness": 4, "completeness": 5}',
        '{"correctness": 5, "faithfulness": 4}',
        "{broken json}",
    ],
)
def test_bedrock_judge_fails_closed_on_a_bad_reply(runtime: tuple[object, Stubber], reply: str) -> None:
    client, stubber = runtime
    item = load_golden_set(GOLDEN_PATH)["gs-001"]
    stubber.add_response("converse", _converse_response(reply))
    with pytest.raises(EvidenceError):
        BedrockJudge(client, "amazon.nova-lite-v1:0", "rubric").score(item, "30 days.")


def test_bedrock_prompt_reads_the_pinned_version() -> None:
    client = boto3.client("bedrock-agent", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    arn = "arn:aws:bedrock:us-east-1:111122223333:prompt/HGSUPPORT1"
    response = {
        "name": "support-answer",
        "id": "HGSUPPORT1",
        "arn": arn,
        "version": "5",
        "createdAt": datetime(2025, 1, 1, tzinfo=UTC),
        "updatedAt": datetime(2025, 1, 1, tzinfo=UTC),
        "defaultVariant": "default",
        "variants": [
            {
                "name": "default",
                "templateType": "TEXT",
                "templateConfiguration": {"text": {"text": "{{context}}{{question}}"}},
            }
        ],
    }
    with Stubber(client) as stubber:
        stubber.add_response("get_prompt", response, {"promptIdentifier": arn, "promptVersion": "5"})
        assert BedrockPrompt(client, arn, "5").template() == "{{context}}{{question}}"
        stubber.add_response("get_prompt", {**response, "version": "DRAFT"})
        with pytest.raises(EvidenceError, match="not 5"):
            BedrockPrompt(client, arn, "5").template()


def test_bedrock_retriever_queries_the_pinned_knowledge_base() -> None:
    client = boto3.client("bedrock-agent-runtime", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    expected = {
        "knowledgeBaseId": "HGPOLICYKB",
        "retrievalQuery": {"text": "Return window?"},
        "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 3}},
    }
    with Stubber(client) as stubber:
        stubber.add_response(
            "retrieve",
            {
                "retrievalResults": [
                    {"content": {"text": "Returns: 30 days."}},
                    {"content": {"text": "Refunds: 5 days."}},
                ]
            },
            expected,
        )
        assert (
            BedrockRetriever(client, "HGPOLICYKB").retrieve("Return window?") == "Returns: 30 days.\n\nRefunds: 5 days."
        )
        stubber.add_response("retrieve", {"retrievalResults": []}, expected)
        with pytest.raises(EvidenceError, match="returned nothing"):
            BedrockRetriever(client, "HGPOLICYKB").retrieve("Return window?")
