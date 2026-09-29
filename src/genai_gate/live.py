"""Amazon Bedrock adapters for the live stage (collect --live).

Only the manual live gate uses these, with short-lived OIDC credentials in CI
or the maintainer's sandbox profile in `make test-live`. The offline tests
drive them through botocore's Stubber, so no request leaves the machine.

APIs: bedrock-agent GetPrompt (the pinned prompt version), bedrock-agent-runtime
Retrieve (the pinned knowledge base), bedrock-runtime Converse (answers and the
judge) and ApplyGuardrail.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from genai_gate.collect import GuardrailReply, ModelReply
from genai_gate.records import METRICS, EvidenceError, GoldenItem, JudgeScore

JUDGE_INSTRUCTIONS = """You grade answers from a retail customer-support assistant.
Use this rubric:

{rubric}

Question: {question}
Retrieved context: {context}
Reference answer: {reference}
Assistant answer: {answer}

Reply with one JSON object and nothing else:
{{"correctness": 1-5, "faithfulness": 1-5, "completeness": 1-5, "rationale": "one sentence"}}"""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# ApplyGuardrail usage fields and the policy names gate/models.yaml prices them under.
USAGE_POLICIES = {
    "contentPolicyUnits": "content",
    "topicPolicyUnits": "denied_topics",
    "sensitiveInformationPolicyUnits": "sensitive_information",
    "wordPolicyUnits": "word",
    "contextualGroundingPolicyUnits": "contextual_grounding",
}
# Usage fields AWS does not bill.
FREE_USAGE = frozenset({"sensitiveInformationPolicyFreeUnits"})


def _converse_text(response: dict[str, Any]) -> str:
    try:
        parts = response["output"]["message"]["content"]
        return "".join(part["text"] for part in parts if "text" in part)
    except (KeyError, TypeError) as exc:
        raise EvidenceError("Converse returned no text content") from exc


class BedrockModel:
    def __init__(self, client: Any, model_id: str, inference: dict[str, Any]) -> None:
        self._client = client
        self._model_id = model_id
        config: dict[str, Any] = {"maxTokens": inference["max_tokens"], "temperature": inference["temperature"]}
        if "top_p" in inference:
            config["topP"] = inference["top_p"]
        self._config = config

    def answer(self, prompt: str) -> ModelReply:
        response = self._client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig=self._config,
        )
        return ModelReply(
            text=_converse_text(response),
            input_tokens=int(response["usage"]["inputTokens"]),
            output_tokens=int(response["usage"]["outputTokens"]),
            latency_ms=int(response["metrics"]["latencyMs"]),
        )


def policy_units(usage: dict[str, Any]) -> dict[str, int]:
    """Billed units per policy. Billed usage the gate cannot price fails the run instead of costing nothing."""
    units: dict[str, int] = {}
    for key, value in usage.items():
        if key in USAGE_POLICIES:
            if int(value):
                units[USAGE_POLICIES[key]] = int(value)
        elif key.endswith("Units") and key not in FREE_USAGE and int(value):
            raise EvidenceError(f"ApplyGuardrail billed {value} units of {key}, which gate/models.yaml does not price")
    return units


class BedrockGuardrail:
    def __init__(self, client: Any, guardrail_id: str, version: str) -> None:
        self._client = client
        self._id = guardrail_id
        self._version = version

    def check(
        self,
        text: str,
        source: Literal["INPUT", "OUTPUT"],
        *,
        grounding_source: str | None = None,
        query: str | None = None,
    ) -> GuardrailReply:
        content: list[dict[str, Any]] = []
        if grounding_source and query:
            # Contextual grounding evaluates guard_content against these two blocks; without them it cannot run.
            content = [
                {"text": {"text": grounding_source, "qualifiers": ["grounding_source"]}},
                {"text": {"text": query, "qualifiers": ["query"]}},
                {"text": {"text": text, "qualifiers": ["guard_content"]}},
            ]
        else:
            content = [{"text": {"text": text}}]
        response = self._client.apply_guardrail(
            guardrailIdentifier=self._id,
            guardrailVersion=self._version,
            source=source,
            content=content,
        )
        intervened = response["action"] == "GUARDRAIL_INTERVENED"
        outputs = response.get("outputs") or []
        # On intervention the guardrail returns the blocked message or the masked text.
        final = outputs[0]["text"] if intervened and outputs else text
        return GuardrailReply(intervened=intervened, text=final, units=policy_units(response.get("usage", {})))


class BedrockPrompt:
    """The pinned version of the managed prompt in Prompt Management."""

    def __init__(self, client: Any, prompt_arn: str, version: str) -> None:
        self._client = client
        self._arn = prompt_arn
        self._version = version

    def template(self) -> str:
        response = self._client.get_prompt(promptIdentifier=self._arn, promptVersion=self._version)
        if str(response.get("version")) != self._version:
            raise EvidenceError(f"GetPrompt returned version {response.get('version')}, not {self._version}")
        variants = response.get("variants") or []
        default = response.get("defaultVariant")
        variant = next((v for v in variants if v.get("name") == default), variants[0] if variants else None)
        try:
            return str(variant["templateConfiguration"]["text"]["text"])  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise EvidenceError(f"prompt {self._arn} version {self._version} has no text template") from exc


class BedrockRetriever:
    """Context from the pinned knowledge base, as the serving path retrieves it."""

    def __init__(self, client: Any, knowledge_base_id: str, results: int = 3) -> None:
        self._client = client
        self._kb = knowledge_base_id
        self._results = results

    def retrieve(self, question: str) -> str:
        response = self._client.retrieve(
            knowledgeBaseId=self._kb,
            retrievalQuery={"text": question},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": self._results}},
        )
        texts = [r["content"]["text"] for r in response.get("retrievalResults", []) if r.get("content", {}).get("text")]
        if not texts:
            raise EvidenceError(f"knowledge base {self._kb} returned nothing for: {question}")
        return "\n\n".join(texts)


class BedrockJudge:
    """LLM-as-judge through Converse. Anything but a valid score object fails the run."""

    def __init__(self, client: Any, model_id: str, rubric: str) -> None:
        self._client = client
        self._model_id = model_id
        self._rubric = rubric

    def score(self, item: GoldenItem, answer: str) -> JudgeScore:
        prompt = JUDGE_INSTRUCTIONS.format(
            rubric=self._rubric, question=item.question, context=item.context, reference=item.reference, answer=answer
        )
        response = self._client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.0},
        )
        text = _converse_text(response)
        match = _JSON_OBJECT.search(text)
        try:
            data = json.loads(match.group(0)) if match else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            raise EvidenceError(f"judge reply for {item.id} is not a JSON object")
        scores = {}
        for metric in METRICS:
            value = data.get(metric)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
                raise EvidenceError(f"judge reply for {item.id}: {metric} must be an integer from 1 to 5")
            scores[metric] = value
        return JudgeScore(id=item.id, rationale=str(data.get("rationale", "")), **scores)
