"""The live stage without the network: fake ports for collect, botocore's Stubber for the Bedrock adapters."""

from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.stub import Stubber
from conftest import ROOT

from genai_gate.collect import GuardrailReply, ModelReply, collect, render, serve
from genai_gate.config import load_catalog, load_policy, load_release
from genai_gate.gate import evaluate, load_inputs
from genai_gate.live import BedrockGuardrail, BedrockJudge, BedrockModel
from genai_gate.records import EvidenceError, GoldenItem, JudgeScore, file_digest, load_golden_set, load_redteam_set

GOLDEN_PATH = ROOT / "evals" / "golden-set.jsonl"
REDTEAM_PATH = ROOT / "evals" / "redteam-set.jsonl"


class FakeModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def answer(self, prompt: str) -> ModelReply:
        self.prompts.append(prompt)
        return ModelReply("I can't help with that. Please check the policy.", 1500, 200, 900)


class FakeGuardrail:
    """Blocks inputs that mention stocks; masks a phone number on output."""

    def check(self, text: str, source: str) -> GuardrailReply:
        if source == "INPUT" and "stocks" in text:
            return GuardrailReply(True, "Sorry, I can't help with that request.", 1)
        if "555-0142" in text:
            return GuardrailReply(True, text.replace("555-0142", "{PHONE}"), 1)
        return GuardrailReply(False, text, 1)


class FakeJudge:
    def score(self, item: GoldenItem, answer: str) -> JudgeScore:
        return JudgeScore(item.id, 5, 5, 4, "fake")


def test_render_requires_both_variables() -> None:
    assert render("{{context}} / {{question}}", question="q", context="c") == "c / q"
    with pytest.raises(ValueError, match="both"):
        render("{{question}} only", question="q", context="c")


def test_serve_skips_the_model_when_the_input_is_blocked() -> None:
    model = FakeModel()
    served = serve("{{context}}{{question}}", "Which stocks should I buy?", "", model, FakeGuardrail())
    assert served.intervened and served.reply is None
    assert model.prompts == []


def test_collect_writes_a_run_the_gate_accepts(tmp_path: Path) -> None:
    release = load_release(ROOT / "release" / "candidate" / "release.yaml")
    model = FakeModel()
    collect(
        release=release,
        golden=load_golden_set(GOLDEN_PATH),
        redteam=load_redteam_set(REDTEAM_PATH),
        set_digests=(file_digest(GOLDEN_PATH), file_digest(REDTEAM_PATH)),
        model=model,
        guardrail=FakeGuardrail(),
        judge=FakeJudge(),
        out_dir=tmp_path / "run",
        source="test",
    )
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
    assert guardrail.check("The phone is 555-0142.", "OUTPUT") == GuardrailReply(True, "The phone is {PHONE}.", 1)
    assert guardrail.check("Plain text", "INPUT") == GuardrailReply(False, "Plain text", 2)


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
