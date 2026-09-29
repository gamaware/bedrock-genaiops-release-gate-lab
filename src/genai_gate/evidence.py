"""Release evidence: the record a reviewer approves, and the audit trail afterwards.

The Markdown goes to the pull request (job summary) and the JSON is kept as a
build artifact. Both are deterministic for the same inputs: no timestamps, no
absolute paths, so a committed evidence file can be checked for drift.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from genai_gate.gate import Decision

WIDTH = 118


def _bullet(text: str) -> list[str]:
    return textwrap.wrap(text, width=WIDTH, initial_indent="- ", subsequent_indent="  ", break_on_hyphens=False)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def to_markdown(decision: Decision, title: str) -> str:
    lines = [f"# Release evidence: {title}", ""]
    lines += textwrap.wrap(f"**Verdict: {decision.verdict}.** {decision.change}", width=WIDTH)
    lines += ["", "## What changed", ""]
    if decision.changes:
        lines += ["| Pin | Baseline (production) | Candidate |", "| --- | --- | --- |"]
        lines += [f"| {_cell(k)} | `{_cell(a)}` | `{_cell(b)}` |" for k, a, b in decision.changes]
    else:
        lines.append("Nothing pinned changed against the production baseline.")
    lines += ["", "## Checks", "", "| Check | Result |", "| --- | --- |"]
    lines += [f"| {check.name} | {'pass' if check.passed else 'BLOCK'} |" for check in decision.checks]
    for check in decision.checks:
        lines += ["", f"### {check.name.capitalize()}", ""]
        lines += ["| Measure | Baseline | Candidate | Limit |", "| --- | --- | --- | --- |"]
        lines += [f"| {_cell(m)} | {_cell(b)} | {_cell(c)} | {_cell(limit)} |" for m, b, c, limit in check.rows]
        if check.findings or check.notes:
            lines.append("")
            for finding in check.findings:
                lines += _bullet(finding)
            for note in check.notes:
                lines += _bullet(f"Note: {note}")
    return "\n".join(lines) + "\n"


def to_json(decision: Decision) -> str:
    payload: dict[str, Any] = {
        "release": decision.release_name,
        "verdict": decision.verdict,
        "change": decision.change,
        "changes": [{"pin": k, "baseline": a, "candidate": b} for k, a, b in decision.changes],
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "findings": check.findings,
                "notes": check.notes,
                "measures": [
                    {"measure": m, "baseline": b, "candidate": c, "limit": limit} for m, b, c, limit in check.rows
                ],
            }
            for check in decision.checks
        ],
    }
    return json.dumps(payload, indent=2) + "\n"
