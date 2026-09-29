"""genai-gate command line.

    genai-gate validate RELEASE                      schema, allowlist and template hash
    genai-gate evaluate --release R --run DIR \\
        --baseline-release B --baseline-run DIR      score a recorded run; exit 0 PASS, 1 BLOCK
    genai-gate collect --release R --out DIR --live  record a run against Amazon Bedrock (live stage only)
    genai-gate serving-config --release R            the JSON value promoted through SSM Parameter Store
    genai-gate check-baseline --baseline-release B \
        --serving-config FILE                        the baseline is what the prod alias serves

Exit codes: 0 pass, 1 blocked, 2 invalid input or incomplete evidence. The
pipeline treats anything but 0 as a blocked release.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from genai_gate.config import ConfigError, load_catalog, load_policy, load_release, release_problems
from genai_gate.evidence import to_json, to_markdown
from genai_gate.gate import evaluate, load_inputs
from genai_gate.records import EvidenceError, file_digest, load_golden_set, load_redteam_set

EXIT_PASS, EXIT_BLOCK, EXIT_INVALID = 0, 1, 2


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--models", type=Path, default=Path("gate/models.yaml"), help="model allowlist and prices")
    parser.add_argument("--policy", type=Path, default=Path("gate/policy.yaml"), help="gate thresholds")
    parser.add_argument("--golden", type=Path, default=Path("evals/golden-set.jsonl"), help="golden question set")
    parser.add_argument("--redteam", type=Path, default=Path("evals/redteam-set.jsonl"), help="red-team prompt set")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="genai-gate", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate a release file")
    validate.add_argument("release", type=Path)
    validate.add_argument("--models", type=Path, default=Path("gate/models.yaml"))

    ev = sub.add_parser("evaluate", help="score a recorded run against the baseline")
    ev.add_argument("--release", type=Path, required=True)
    ev.add_argument("--run", type=Path, required=True)
    ev.add_argument("--baseline-release", type=Path, required=True)
    ev.add_argument("--baseline-run", type=Path, required=True)
    ev.add_argument("--evidence-dir", type=Path, help="write evidence.md and evidence.json here")
    ev.add_argument("--title", help="evidence title (default: the release name)")
    _common(ev)

    col = sub.add_parser("collect", help="record a run against Amazon Bedrock")
    col.add_argument("--release", type=Path, required=True)
    col.add_argument("--out", type=Path, required=True)
    col.add_argument("--live", action="store_true", help="required: confirms this calls Amazon Bedrock")
    col.add_argument("--region", default="us-east-1")
    col.add_argument("--judge-model", default="amazon.nova-lite-v1:0")
    col.add_argument("--rubric", type=Path, default=Path("evals/rubric.md"))
    _common(col)

    serving = sub.add_parser("serving-config", help="print the SSM parameter value for a release")
    serving.add_argument("--release", type=Path, required=True)

    baseline = sub.add_parser("check-baseline", help="check the baseline is the release production serves")
    baseline.add_argument("--baseline-release", type=Path, required=True)
    baseline.add_argument("--serving-config", type=Path, required=True, help="the prod alias's SSM parameter value")
    return parser


def _validate(args: argparse.Namespace) -> int:
    release = load_release(args.release)
    problems = release_problems(release, load_catalog(args.models))
    for problem in problems:
        print(f"{args.release}: {problem}", file=sys.stderr)
    if problems:
        return EXIT_BLOCK
    print(f"{args.release}: valid (release digest {release.digest[:12]})")
    return EXIT_PASS


def _evaluate(args: argparse.Namespace) -> int:
    release = load_release(args.release)
    inputs = load_inputs(
        release=release,
        run_dir=args.run,
        baseline_release=load_release(args.baseline_release),
        baseline_dir=args.baseline_run,
        golden_path=args.golden,
        redteam_path=args.redteam,
        catalog=load_catalog(args.models),
        policy=load_policy(args.policy),
    )
    decision = evaluate(inputs)
    markdown = to_markdown(decision, args.title or decision.release_name)
    if args.evidence_dir:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "evidence.md").write_text(markdown, encoding="utf-8")
        (args.evidence_dir / "evidence.json").write_text(to_json(decision), encoding="utf-8")
    print(markdown, end="")
    return EXIT_PASS if decision.passed else EXIT_BLOCK


def _collect(args: argparse.Namespace) -> int:
    if not args.live:
        print("collect calls Amazon Bedrock; pass --live to confirm", file=sys.stderr)
        return EXIT_INVALID
    import boto3  # optional dependency: only the live stage installs it

    from genai_gate.collect import collect
    from genai_gate.live import BedrockGuardrail, BedrockJudge, BedrockModel, BedrockPrompt, BedrockRetriever

    release = load_release(args.release)
    problems = release_problems(release, load_catalog(args.models))
    if problems:
        print("; ".join(problems), file=sys.stderr)
        return EXIT_BLOCK
    client = boto3.client("bedrock-runtime", region_name=args.region)
    guardrail = release.data["guardrail"]
    prompt = release.data["prompt"]
    collect(
        release=release,
        golden=load_golden_set(args.golden),
        redteam=load_redteam_set(args.redteam),
        set_digests=(file_digest(args.golden), file_digest(args.redteam)),
        prompt=BedrockPrompt(boto3.client("bedrock-agent", region_name=args.region), prompt["arn"], prompt["version"]),
        retriever=BedrockRetriever(
            boto3.client("bedrock-agent-runtime", region_name=args.region), release.data["knowledge_base"]["id"]
        ),
        model=BedrockModel(client, release.model_id, release.data["model"]["inference"]),
        guardrail=BedrockGuardrail(client, guardrail["id"], guardrail["version"]),
        judge=BedrockJudge(client, args.judge_model, args.rubric.read_text(encoding="utf-8")),
        out_dir=args.out,
        source=f"live:{release.model_id}:judge={args.judge_model}",
    )
    print(f"recorded run in {args.out}")
    return EXIT_PASS


def serving_config(release_path: Path) -> dict[str, object]:
    release = load_release(release_path)
    data = release.data
    return {
        "release": data["release"]["name"],
        "release_digest": release.digest,
        "model_id": data["model"]["id"],
        "inference": data["model"]["inference"],
        "prompt_arn": data["prompt"]["arn"],
        "prompt_version": data["prompt"]["version"],
        "guardrail_id": data["guardrail"]["id"],
        "guardrail_version": data["guardrail"]["version"],
        "knowledge_base_id": data["knowledge_base"]["id"],
    }


UNSET = {"release": "unset"}


def baseline_problem(baseline_path: Path, serving: object) -> str | None:
    """Why the committed baseline is not the release the prod alias serves, or None if it is.

    Promotion and rollback change the prod alias; the baseline in
    release/production must follow them, or the gate compares candidates
    with a release customers no longer get.
    """
    baseline = load_release(baseline_path)
    if serving == UNSET:
        return None  # nothing promoted yet: the committed baseline is the only reference
    if not isinstance(serving, dict) or not isinstance(serving.get("release_digest"), str):
        return "the prod serving configuration has no release_digest"
    served = serving["release_digest"]
    if served != baseline.digest:
        return (
            f"prod serves release {served[:12]}, but the baseline {baseline_path} is {baseline.digest[:12]}: "
            "commit the promoted release and its recorded run to release/production, then gate again"
        )
    return None


def _check_baseline(args: argparse.Namespace) -> int:
    try:
        serving = json.loads(args.serving_config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{args.serving_config}: cannot read the serving configuration ({exc})") from exc
    problem = baseline_problem(args.baseline_release, serving)
    if problem:
        print(f"genai-gate: {problem}", file=sys.stderr)
        return EXIT_BLOCK
    if serving == UNSET:
        print("prod alias is unset: nothing promoted yet, gating against the committed baseline")
    else:
        print(f"baseline {args.baseline_release} is the release prod serves")
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args)
        if args.command == "evaluate":
            return _evaluate(args)
        if args.command == "collect":
            return _collect(args)
        if args.command == "check-baseline":
            return _check_baseline(args)
        print(json.dumps(serving_config(args.release), sort_keys=True, separators=(",", ":")))
        return EXIT_PASS
    except (ConfigError, EvidenceError) as exc:
        print(f"genai-gate: {exc}", file=sys.stderr)
        print("genai-gate: BLOCK (invalid input or incomplete evidence)", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
