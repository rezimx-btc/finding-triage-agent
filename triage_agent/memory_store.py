"""Verdict memory store: the session memory of past triage verdicts.

A verdict is stored as JSON in one local file (``memory_store.json``) so it
survives across runs: the next run consults it first and never triages the
same bug twice. Recall is a deterministic token-overlap score -- pure
functions, unit-tested in ``tests/`` -- so dedup does not depend on the
model's mood. The model sees the recall matches and makes the final
duplicate call; the store only ranks candidates.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

SEVERITIES = ("Critical", "High", "Medium", "Low", "Info")
STATUSES = ("accept", "duplicate", "reject")

_STOPWORDS = frozenset(
    "the a an and or of in on to for with is are was were be been it its this that "
    "there here as at by from into about over under after before between when where "
    "which who whom what how why not no yes if then than so such very just only also "
    "we you they he she his her their our your my me him them us i".split()
)


def tokenize(text: str) -> set[str]:
    """Lowercase word tokens, stopwords removed."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def overlap_score(a: str, b: str) -> float:
    """Jaccard-style overlap of token sets: 0.0 (unrelated) .. 1.0 (identical)."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def recall_key(finding: dict) -> str:
    """Text used for recall: title + target + body."""
    return " ".join(
        [
            str(finding.get("title", "")),
            str(finding.get("target", "")),
            str(finding.get("body", ""))[:2000],
        ]
    )


class VerdictStore:
    """JSON-backed store of past verdicts (the agent's session memory)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.verdicts: list[dict] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.verdicts = data.get("verdicts", []) if isinstance(data, dict) else []
            except (json.JSONDecodeError, OSError):
                self.verdicts = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"version": 1, "verdicts": self.verdicts},
                indent=2,
                ensure_ascii=False,
            )
        )

    def add(self, verdict: dict) -> dict:
        verdict = dict(verdict)
        verdict.setdefault("stored_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.verdicts.append(verdict)
        self.save()
        return verdict

    def recall(self, finding: dict, top_n: int = 3, min_score: float = 0.18) -> list[dict]:
        """Rank past ACCEPTED verdicts by token overlap with this finding."""
        query = recall_key(finding)
        scored = []
        for v in self.verdicts:
            if v.get("status") != "accept":
                continue
            past = recall_key(
                {"title": v.get("title", ""), "target": v.get("target", ""), "body": v.get("body", "")}
            )
            score = overlap_score(query, past)
            if score >= min_score:
                scored.append({**v, "recall_score": round(score, 3)})
        scored.sort(key=lambda d: d["recall_score"], reverse=True)
        return scored[:top_n]

    def get(self, finding_id: str) -> dict | None:
        for v in self.verdicts:
            if v.get("finding_id") == finding_id:
                return v
        return None
