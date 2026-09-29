"""Release file, gate policy and model allowlist.

The release digest identifies exactly what was evaluated: the pinned model,
inference settings, prompt version and template hash, guardrail version and
knowledge base. A recorded run carries the digest of the release it was
produced for, so evidence from one release can never pass another.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from genai_gate.records import file_digest


class ConfigError(ValueError):
    """A release, policy or allowlist file is missing or invalid."""


@dataclass(frozen=True)
class Release:
    path: Path
    data: dict[str, Any]

    @property
    def model_id(self) -> str:
        return str(self.data["model"]["id"])

    @property
    def guardrail_policies(self) -> tuple[str, ...]:
        return tuple(self.data["guardrail"]["policies"])

    @property
    def template_path(self) -> Path:
        return self.path.parent / self.data["prompt"]["template_file"]

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def pins(self) -> dict[str, str]:
        """The flat view used to describe what changed between two releases."""
        data = self.data
        chunking = data["knowledge_base"]["chunking"]
        return {
            "model": data["model"]["id"],
            "inference": json.dumps(data["model"]["inference"], sort_keys=True),
            "prompt": f"{data['prompt']['arn']}:{data['prompt']['version']}",
            "prompt template": data["prompt"]["template_sha256"][:12],
            "guardrail": f"{data['guardrail']['id']}:{data['guardrail']['version']}",
            "guardrail policies": ",".join(sorted(data["guardrail"]["policies"])),
            "knowledge base": data["knowledge_base"]["id"],
            "chunking": f"{chunking['strategy']}/{chunking['max_tokens']}/{chunking['overlap_percentage']}",
        }


@dataclass(frozen=True)
class ModelPrice:
    input_per_1m_tokens: float
    output_per_1m_tokens: float


@dataclass(frozen=True)
class Catalog:
    models: dict[str, ModelPrice]
    guardrail_per_1k_text_units: dict[str, float]


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"{path}: file not found")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})") from exc


def _schema() -> dict[str, Any]:
    text = Path(__file__).with_name("release.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def schema_errors(data: Any) -> list[str]:
    validator = Draft202012Validator(_schema())
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        errors.append(f"{location}: {error.message}")
    return errors


def load_release(path: Path) -> Release:
    """Load a release file. Raises ConfigError if it does not match the schema."""
    data = _load_yaml(path)
    errors = schema_errors(data)
    if errors:
        raise ConfigError(f"{path}: " + "; ".join(errors))
    return Release(path=path, data=data)


def release_problems(release: Release, catalog: Catalog) -> list[str]:
    """Checks beyond the schema: allowlist, template hash and pricing coverage."""
    problems = []
    if release.model_id not in catalog.models:
        problems.append(f"model {release.model_id} is not in the allowlist")
    template = release.template_path
    if not template.is_file():
        problems.append(f"prompt template {template} not found")
    elif file_digest(template) != release.data["prompt"]["template_sha256"]:
        problems.append(f"prompt template {template.name} does not match template_sha256 (edited without a new pin)")
    unpriced = [p for p in release.guardrail_policies if p not in catalog.guardrail_per_1k_text_units]
    if unpriced:
        problems.append(f"guardrail policies without a price: {', '.join(unpriced)}")
    return problems


def load_catalog(path: Path) -> Catalog:
    raw = _load_yaml(path)
    try:
        models = {
            model_id: ModelPrice(float(entry["input_per_1m_tokens"]), float(entry["output_per_1m_tokens"]))
            for model_id, entry in raw["models"].items()
        }
        guardrail = {name: float(price) for name, price in raw["guardrail_per_1k_text_units"].items()}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ConfigError(f"{path}: expected models.<id>.{{input,output}}_per_1m_tokens and guardrail prices") from exc
    if not models:
        raise ConfigError(f"{path}: the allowlist is empty")
    return Catalog(models=models, guardrail_per_1k_text_units=guardrail)


@dataclass(frozen=True)
class Policy:
    min_mean: dict[str, float]
    max_mean_drop: float
    critical_min_correctness: int
    max_item_regressions: int
    redteam_min_pass_rate: dict[str, float]
    block_on_regression: bool
    refusal_markers: tuple[str, ...]
    max_usd_per_1k_requests: float
    max_increase_pct: float
    max_p95_latency_ms: int


def load_policy(path: Path) -> Policy:
    raw = _load_yaml(path)
    try:
        quality, redteam, cost = raw["quality"], raw["redteam"], raw["cost"]
        policy = Policy(
            min_mean={str(k): float(v) for k, v in quality["min_mean"].items()},
            max_mean_drop=float(quality["max_mean_drop"]),
            critical_min_correctness=int(quality["critical_min_correctness"]),
            max_item_regressions=int(quality["max_item_regressions"]),
            redteam_min_pass_rate={str(k): float(v) for k, v in redteam["min_pass_rate"].items()},
            block_on_regression=bool(redteam["block_on_regression"]),
            refusal_markers=tuple(str(m) for m in redteam["refusal_markers"]),
            max_usd_per_1k_requests=float(cost["max_usd_per_1k_requests"]),
            max_increase_pct=float(cost["max_increase_pct"]),
            max_p95_latency_ms=int(cost["max_p95_latency_ms"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ConfigError(f"{path}: missing or invalid key ({exc})") from exc
    if not policy.refusal_markers:
        raise ConfigError(f"{path}: redteam.refusal_markers must not be empty")
    return policy
