"""OpenMinion tools for the Finding Triage Agent.

Four tools, all declared with ``@openminion.tool`` and executed through the
OpenMinion runtime (tool use is logged by the runtime; every call is visible
in the run diagnostics):

- ``read_finding``   -- read + parse one raw finding file (.md / .json).
- ``recall_verdicts``-- search the session memory for the same root cause.
- ``record_verdict`` -- the model-backed judgement, captured as structured
  arguments (severity / confidence / reason / duplicate link). The tool
  VALIDATES the verdict (enum + ranges) and persists it to session memory;
  it does not invent the judgement -- the model supplies it.
- ``draft_report``   -- write the structured report file for one finding.

Tools read their runtime context (store, reports dir, current finding) from
the module-level ``CTX`` dict, set by the orchestrator before each run.
Runs are sequential, so one context slot is enough.
"""
from __future__ import annotations

import json
from pathlib import Path

from openminion import tool

from .memory_store import SEVERITIES, STATUSES, VerdictStore, recall_key

CTX: dict = {"store": None, "reports_dir": None, "current_finding": None}


def parse_finding_file(path: str | Path) -> dict:
    """Parse a raw finding file. .json = fields; .md = title + body."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        return {
            "id": data.get("id") or p.stem,
            "title": str(data.get("title", "")).strip(),
            "target": str(data.get("target", "")).strip(),
            "body": str(data.get("body", "")).strip(),
            "source": str(p),
        }
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = ""
    for ln in lines:
        if ln.startswith("#"):
            title = ln.lstrip("#").strip()
            break
    if not title and lines:
        title = lines[0]
    target = ""
    for ln in lines:
        if ln.lower().startswith("target:"):
            target = ln.split(":", 1)[1].strip()
            break
    return {
        "id": p.stem,
        "title": title,
        "target": target,
        "body": text.strip(),
        "source": str(p),
    }


def validate_verdict(
    status: str, severity: str, confidence: float, reason: str, duplicate_of: str = ""
) -> list[str]:
    """Deterministic guardrails on a model-supplied verdict. Returns errors."""
    errors = []
    if status not in STATUSES:
        errors.append(f"status must be one of {STATUSES}, got {status!r}")
    if status == "accept" and severity not in SEVERITIES:
        errors.append(f"severity must be one of {SEVERITIES}, got {severity!r}")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        errors.append(f"confidence must be a number 0..1, got {confidence!r}")
    if not reason or len(reason.strip()) < 10:
        errors.append("reason must be at least 10 characters citing the evidence")
    if duplicate_of and status != "duplicate":
        errors.append("duplicate_of is only valid when status is 'duplicate'")
    if status == "duplicate" and not duplicate_of:
        errors.append("status 'duplicate' requires duplicate_of (a past finding id)")
    return errors


@tool(
    name="read_finding",
    description="Read and parse one raw finding file (markdown or JSON). Returns title, target and body.",
)
def read_finding(path: str) -> str:
    """Read + parse a raw finding file."""
    try:
        finding = parse_finding_file(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return json.dumps({"error": f"cannot read finding: {exc}"})
    return json.dumps(finding, ensure_ascii=False)


@tool(
    name="recall_verdicts",
    description="Search session memory for past verdicts with the same root cause, target or pattern. Returns ranked matches with overlap scores.",
)
def recall_verdicts(title: str, target: str, text: str) -> str:
    """Search session memory for the same root cause / target / pattern."""
    store: VerdictStore | None = CTX.get("store")
    if store is None:
        return json.dumps({"error": "memory store not initialised"})
    matches = store.recall({"title": title, "target": target, "body": text})
    return json.dumps(
        [
            {
                "finding_id": m.get("finding_id"),
                "title": m.get("title"),
                "severity": m.get("severity"),
                "recall_score": m.get("recall_score"),
            }
            for m in matches
        ],
        ensure_ascii=False,
    )


@tool(
    name="record_verdict",
    description="Record the triage verdict for the current finding: status accept/duplicate/reject, severity, confidence 0-1, one-paragraph reason citing the evidence, and duplicate_of when it duplicates a past finding.",
)
def record_verdict(
    status: str,
    severity: str,
    confidence: float,
    reason: str,
    duplicate_of: str = "",
) -> str:
    """Validate + persist the model's verdict for the current finding."""
    store: VerdictStore | None = CTX.get("store")
    finding: dict | None = CTX.get("current_finding")
    if store is None or finding is None:
        return json.dumps({"error": "verdict context not initialised"})
    errors = validate_verdict(status, severity, confidence, reason, duplicate_of)
    if errors:
        return json.dumps({"error": "; ".join(errors)})
    verdict = {
        "finding_id": finding["id"],
        "title": finding["title"],
        "target": finding.get("target", ""),
        "body": finding.get("body", "")[:2000],
        "status": status,
        "severity": severity if status == "accept" else "",
        "confidence": float(confidence),
        "reason": reason.strip(),
        "duplicate_of": duplicate_of or "",
    }
    store.add(verdict)
    return json.dumps({"recorded": True, "finding_id": finding["id"], "status": status})


def render_report(finding: dict, verdict: dict) -> str:
    """Structured report markdown (the format the researcher files)."""
    sev = verdict.get("severity") or "—"
    lines = [
        f"# {finding['title']}",
        "",
        f"- **Severity:** {sev}",
        f"- **Confidence:** {verdict.get('confidence', 0):.2f}",
        f"- **Status:** {verdict.get('status', '')}",
        f"- **Target:** {finding.get('target') or '—'}",
        f"- **Source:** {finding.get('source', '')}",
        "",
        "## Summary",
        "",
        verdict.get("reason", ""),
        "",
        "## Evidence (raw finding)",
        "",
        finding.get("body", "")[:3000],
        "",
        "## Suggested fix",
        "",
        "Fix the root cause described above, re-test the exact repro, and "
        "re-run the checks that produced this finding before closing it.",
        "",
        "---",
        "_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval "
        "required before filing anywhere._",
        "",
    ]
    return "\n".join(lines)


@tool(
    name="draft_report",
    description="Write the structured report markdown file for one accepted finding. Takes the finding id only; the report is rendered from the stored verdict.",
)
def draft_report(finding_id: str) -> str:
    """Write reports/<finding_id>.md from the stored verdict."""
    store: VerdictStore | None = CTX.get("store")
    reports_dir: Path | None = CTX.get("reports_dir")
    if store is None or reports_dir is None:
        return json.dumps({"error": "report context not initialised"})
    verdict = store.get(finding_id)
    if verdict is None:
        return json.dumps({"error": f"no verdict stored for {finding_id}"})
    if verdict.get("status") != "accept":
        return json.dumps({"error": f"finding {finding_id} is not accepted, no report"})
    finding = {
        "id": verdict["finding_id"],
        "title": verdict["title"],
        "target": verdict.get("target", ""),
        "body": verdict.get("body", ""),
        "source": "",
    }
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"{finding_id}.md"
    out.write_text(render_report(finding, verdict), encoding="utf-8")
    return json.dumps({"report": str(out)})
