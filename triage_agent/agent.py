"""Finding Triage Agent — orchestrator.

One OpenMinion agent execution (one delegated sub-task) per finding, all
sharing a single APIRuntime:

1. ingest  -- read raw findings from a folder (.md / .json)
2. dedup   -- the orchestrator recalls past verdicts deterministically
              (token-overlap) and embeds the matches in the run message;
              the model makes the final duplicate call, linked to the
              original finding
3. score   -- the model judges severity + confidence + reason and captures
              it with ``record_verdict`` (structured tool args, forced).
              The verdict is durable the moment the tool executes, so a
              later rate-limited finalize turn cannot lose it.
4. draft   -- the orchestrator writes the structured report file from the
              stored verdict (``draft_report`` is also available as a tool)
5. remember-- every verdict is already in the store before the next finding
6. report  -- run summary printed + saved as JSON, with per-finding
              diagnostics (tokens, calls, attempts, model, duration)

Model route: Groq via OpenMinion's native ``groq`` provider
(OpenAI-compatible, ``GROQ_API_KEY`` env). Free tier is 8,000 TPM per
model, and one triage turn costs ~2-3k input tokens with follow-ups, so
the orchestrator ROTATES two models (gpt-oss-20b / gpt-oss-120b), paces
runs, and retries rate-limit failures with a 70 s backoff instead of
failing the run. Nothing is faked: a finding the model cannot judge is
reported as ``model_error``, never invented.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

# --- environment fix (must run before openminion/httpx read proxy env) ------
# httpx (used by OpenMinion's provider transport, trust_env=True) crashes on
# this VM's NO_PROXY value, which contains bracketed IPv6 entries
# ("InvalidURL: Invalid port: ':1]'"). Narrow it to loopback only.
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

from pydantic import BaseModel, Field  # noqa: E402

from openminion import Agent, APIRuntime, ProviderError  # noqa: E402

from . import tools as triage_tools  # noqa: E402
from .memory_store import SEVERITIES, STATUSES, VerdictStore  # noqa: E402
from .tools import parse_finding_file, record_verdict  # noqa: E402,E501

# Groq free tier: 8,000 TPM per model. gpt-oss-20b's DAILY budget
# (200k TPD) was exhausted by shared org use on 21 Nov 2026
# (Used 199,582 at ~20:30 WIB), so the default rotation is 120b + qwen.
MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
MAX_ATTEMPTS = 3

SCORER_INSTRUCTIONS = (
    "You are a security-triage scorer. Work this ONE finding only.\n"
    "The PAST SIMILAR VERDICTS section in the message is the session-memory\n"
    "recall for this finding (already computed). Judge it: if a recalled\n"
    "verdict has the SAME root cause, it is a duplicate (record\n"
    "duplicate_of=<that finding id>). If the text has no concrete evidence\n"
    "(no target, no repro, no observable effect), reject it. Otherwise\n"
    "accept it with severity Critical/High/Medium/Low/Info, confidence\n"
    "0..1, and a one-paragraph reason citing the evidence.\n"
    "Capture the judgement with record_verdict (required).\n"
    "Reply with one line: VERDICT <accept|duplicate|reject> <severity or -> "
    "<confidence>. (When you submit your final answer, set domain to 'general'.)"
)


def groq_remaining_tokens(model: str) -> tuple[int | None, float | None]:
    """Probe Groq's remaining TPM budget for one model (costs ~10 tokens).

    Returns (remaining_tokens, reset_seconds) from the response headers, or
    (None, None) when the probe itself fails -- the caller then proceeds
    best-effort. The probe goes through the same surrogate mechanism as the
    Groq connector helper (never the real key).
    """
    import json as _json
    import urllib.request

    try:
        sys_path = "/opt/muse/skills/custom-connector-setup/bin"
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from dynamic_credentials import add_surrogate_to_request

        body = _json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=body, method="POST"
        )
        req.add_header("User-Agent", "curl/8.5.0")
        req.add_header("Content-Type", "application/json")
        add_surrogate_to_request(req, "custom.groq", allowed_hosts=["api.groq.com"])

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                raise RuntimeError("redirect refused")

        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=30) as resp:
            remaining = resp.headers.get("x-ratelimit-remaining-tokens")
            reset_raw = resp.headers.get("x-ratelimit-reset-tokens") or ""
            # Reset header format varies ("25.342s", "1m5s"); parse defensively.
            import re as _re

            m = _re.search(r"([\d.]+)s\s*$", reset_raw.strip())
            reset = float(m.group(1)) if m else None
            return (
                int(remaining) if remaining else None,
                reset,
            )
    except Exception:
        return None, None


def wait_for_headroom(model: str, need: int = 7000, timeout_s: float = 300.0) -> bool:
    """Wait until Groq reports >= ``need`` TPM remaining for ``model``.

    Groq's free tier is 8,000 TPM per model and this org is shared, so a
    run started blind can 429 on its first follow-up call. Poll the cheap
    1-token probe; a failed probe means "unknown", NOT "go" -- keep waiting
    until the deadline, then proceed best-effort.
    """
    deadline = time.time() + timeout_s
    while True:
        remaining, reset = groq_remaining_tokens(model)
        if remaining is None:
            print(f"    [tpm] probe failed for {model} (unknown headroom), retrying ...")
        else:
            print(f"    [tpm] {model}: {remaining} tokens remaining (reset {reset}s)")
            if remaining >= need:
                return True
        if time.time() > deadline:
            print(f"    [tpm] headroom timeout ({need} not reached), proceeding anyway")
            return False
        time.sleep(20)


class TriageVerdict(BaseModel):
    """Structured final output of one triage run (validated by the runtime)."""

    status: str = Field(description="accept, duplicate or reject")
    severity: str = Field(default="", description="Critical/High/Medium/Low/Info, or empty")
    confidence: float = Field(default=0.0, description="0..1")
    reason: str = Field(default="", description="one paragraph citing the evidence")
    duplicate_of: str = Field(default="", description="past finding id when duplicate")


def resolve_groq_key() -> str | None:
    """GROQ_API_KEY from env, else a fresh Muse-connector surrogate (VM-only).

    The surrogate (``hsurr:...``) is NOT the real key: Sentinel swaps it for
    the real credential on approved egress to api.groq.com. It is fetched
    fresh for every run and never written to disk or logs.
    """
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    try:
        import sys

        sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
        from dynamic_credentials import dynamic_credential_entry

        entry = dynamic_credential_entry("custom.groq")
        return str(entry["surrogate"]).strip()
    except Exception:
        return None


def _is_rate_limited(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return "RATE_LIMITED" in text or "rate limited" in text.lower() or "429" in text


class TriageAgent:
    """Orchestrates one triage run over a folder of raw findings."""

    def __init__(
        self,
        *,
        findings_dir: str | Path,
        reports_dir: str | Path,
        store_path: str | Path,
        project_root: str | Path | None = None,
        pace_seconds: float = 25.0,
        models: list[str] | None = None,
        provider: str = "groq",
        config_path: str | Path | None = None,
    ):
        self.findings_dir = Path(findings_dir)
        self.reports_dir = Path(reports_dir)
        self.store = VerdictStore(store_path)
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.pace_seconds = pace_seconds
        self.models = models or MODELS
        self.provider = provider
        self.config_path = str(config_path) if config_path else None
        self.run_id = uuid.uuid4().hex[:12]
        self.runtime: APIRuntime | None = None
        self.summary: dict = {}

    # -- runtime / permissions -------------------------------------------
    def _approval(self, name: str, args: dict, reason: str) -> bool:
        """Permissions: auto-allow ONLY our own triage tools; deny the rest.

        Our tools are read-only on inputs and write only to reports/ and
        the memory store (declared scope). Anything else the model tries to
        call is denied and logged.
        """
        allowed = {"read_finding", "recall_verdicts", "record_verdict", "draft_report"}
        ok = name in allowed
        print(f"    [permission] {'ALLOW' if ok else 'DENY '} tool={name} reason={reason[:60]}")
        return ok

    def _ensure_runtime(self) -> APIRuntime:
        if self.runtime is None:
            if self.provider == "groq":
                key = resolve_groq_key()
                if not key:
                    raise RuntimeError(
                        "No Groq key: set GROQ_API_KEY, or run on the Muse VM where "
                        "the custom.groq connector can issue a surrogate."
                    )
                os.environ["GROQ_API_KEY"] = key
            # Project-scoped config: ./.openminion/agents.json (groq) or the
            # explicit config_path (e.g. .openminion/agents-ollama.json).
            self.runtime = APIRuntime.from_config_path(
                self.config_path, logging_mode="interactive"
            )
        return self.runtime

    # -- ingest ------------------------------------------------------------
    def ingest(self) -> list[dict]:
        findings = []
        for path in sorted(self.findings_dir.iterdir()):
            if path.suffix.lower() not in (".md", ".json") or not path.is_file():
                continue
            try:
                findings.append(parse_finding_file(path))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"    [ingest] SKIP {path.name}: {exc}")
        return findings

    # -- one finding, one delegated agent run ------------------------------
    def triage_one(self, finding: dict, model_index: int = 0) -> dict:
        """Run one delegated scorer agent for one finding, with retries.

        Retries ROTATE models (each Groq model has its own 8,000 TPM
        budget), and the first attempt waits for TPM headroom first.
        """
        runtime = self._ensure_runtime()
        triage_tools.CTX["store"] = self.store
        triage_tools.CTX["reports_dir"] = self.reports_dir
        triage_tools.CTX["current_finding"] = finding
        session_id = f"triage-{self.run_id}-{finding['id']}"
        # Dedup recall is computed deterministically by the orchestrator and
        # embedded in the message (each extra model turn costs ~1.5k tokens
        # against an 8,000 TPM shared budget -- see BUILDING_BLOCKS.md).
        # The duplicate DECISION stays with the model.
        recalled = self.store.recall(finding)
        if recalled:
            recall_lines = "\n".join(
                f"- {m['finding_id']}: {m['title']} (severity {m.get('severity')}, overlap {m['recall_score']})"
                for m in recalled
            )
            recall_block = f"\nPAST SIMILAR VERDICTS (session memory):\n{recall_lines}"
        else:
            recall_block = "\nPAST SIMILAR VERDICTS (session memory): none."
        message = (
            f"Triage this finding.\n"
            f"finding_id={finding['id']}\n"
            f"title={finding['title']}\n"
            f"target={finding.get('target') or '-'}\n"
            f"text={finding.get('body', '')[:1200]}"
            f"{recall_block}"
        )
        diag: dict = {
            "finding_id": finding["id"],
            "title": finding["title"],
            "model": "",
            "attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "duration_s": 0.0,
        }
        t0 = time.time()
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            model = self.models[(model_index + attempt - 1) % len(self.models)]
            diag["model"] = model
            diag["attempts"] = attempt
            if attempt == 1 and self.provider == "groq":
                wait_for_headroom(model)
            agent = Agent(
                instructions=SCORER_INSTRUCTIONS,
                model=model,
                tools=[record_verdict],
                forced_tools=["record_verdict"],
                output_type=TriageVerdict,
                runtime=runtime,
                session_id=f"{session_id}-a{attempt}",
                name=f"scorer-{finding['id']}",
            )
            try:
                result = agent.run(
                    message, timeout_seconds=180, approval_callback=self._approval
                )
                stats = getattr(result, "stats", {}) or {}
                diag["input_tokens"] += int(stats.get("input_tokens") or 0)
                diag["output_tokens"] += int(stats.get("output_tokens") or 0)
                diag["llm_calls"] += int(stats.get("llm_calls") or 0)
                diag["tool_calls"] += int(stats.get("tool_calls") or 0)
                verdict = self._reconcile(finding, result)
                if verdict is not None:
                    diag.update(verdict)
                    break
                last_error = "model produced no usable verdict (no record_verdict call and no valid structured output)"
                print(f"    [attempt {attempt}] {last_error}")
            except Exception as exc:  # noqa: BLE001 - report, then retry or fail
                last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                print(f"    [attempt {attempt}] FAILED: {last_error}")
                # Resilience: the verdict is durable the moment the model
                # calls record_verdict. A later call (e.g. the finalize /
                # submit_output turn) may still 429 -- if the verdict is
                # already in the store, the finding is DONE, not an error.
                stored = self.store.get(finding["id"])
                if stored is not None:
                    print("    [attempt {}] verdict already recorded despite the error".format(attempt))
                    diag.update(
                        {
                            "status": stored["status"],
                            "severity": stored.get("severity", ""),
                            "confidence": stored.get("confidence", 0.0),
                            "reason": stored.get("reason", ""),
                            "duplicate_of": stored.get("duplicate_of", ""),
                            "verdict_source": "record_verdict tool (finalize failed)",
                        }
                    )
                    break
                if _is_rate_limited(exc) and attempt < MAX_ATTEMPTS:
                    next_model = self.models[(model_index + attempt) % len(self.models)]
                    print(f"    [retry] rate-limited, waiting for headroom on {next_model} ...")
                    if self.provider == "groq":
                        wait_for_headroom(next_model)
                    else:
                        time.sleep(10)
                    continue
                if attempt < MAX_ATTEMPTS and "AgentOutputValidationError" in type(exc).__name__:
                    continue
                break
            finally:
                agent.close()
        diag["duration_s"] = round(time.time() - t0, 1)
        if "status" not in diag:
            diag.update(
                {
                    "status": "model_error",
                    "severity": "",
                    "confidence": 0.0,
                    "reason": last_error or "no verdict produced",
                    "duplicate_of": "",
                }
            )
        return diag

    def _reconcile(self, finding: dict, result) -> dict | None:
        """Prefer the tool-recorded verdict; fall back to structured output."""
        stored = self.store.get(finding["id"])
        if stored is not None:
            return {
                "status": stored["status"],
                "severity": stored.get("severity", ""),
                "confidence": stored.get("confidence", 0.0),
                "reason": stored.get("reason", ""),
                "duplicate_of": stored.get("duplicate_of", ""),
                "verdict_source": "record_verdict tool",
            }
        output = getattr(result, "output", None)
        if isinstance(output, TriageVerdict):
            errors = []
            from .tools import validate_verdict

            errors = validate_verdict(output.status, output.severity, output.confidence, output.reason)
            if output.status not in STATUSES:
                errors.append(f"bad status {output.status!r}")
            if not errors:
                verdict = {
                    "finding_id": finding["id"],
                    "title": finding["title"],
                    "target": finding.get("target", ""),
                    "body": finding.get("body", "")[:2000],
                    "status": output.status,
                    "severity": output.severity if output.status == "accept" else "",
                    "confidence": float(output.confidence),
                    "reason": output.reason.strip(),
                    "duplicate_of": output.duplicate_of or "",
                }
                self.store.add(verdict)
                return {**verdict, "verdict_source": "structured output (fallback)"}
        return None

    def _write_report_if_needed(self, finding: dict, diag: dict) -> str:
        """Guarantee the report file exists for accepted findings."""
        if diag.get("status") != "accept":
            return ""
        out = self.reports_dir / f"{finding['id']}.md"
        if out.exists():
            return f"{out} (via draft_report tool)"
        from .tools import render_report

        verdict = self.store.get(finding["id"])
        if verdict is None:
            return ""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(render_report(finding, verdict), encoding="utf-8")
        return f"{out} (via orchestrator fallback)"

    # -- full run ------------------------------------------------------------
    def run(self, limit: int | None = None) -> dict:
        t0 = time.time()
        findings = self.ingest()
        if limit:
            findings = findings[:limit]
        print(f"[triage] run {self.run_id}: {len(findings)} findings from {self.findings_dir}")
        results = []
        try:
            for i, finding in enumerate(findings):
                model = self.models[i % len(self.models)]
                print(f"\n[{i+1}/{len(findings)}] {finding['id']}: {finding['title']} (model {model})")
                diag = self.triage_one(finding, i)
                diag["report"] = self._write_report_if_needed(finding, diag)
                print(
                    f"    -> {diag['status']} {diag.get('severity') or ''} "
                    f"conf={diag.get('confidence', 0):.2f} "
                    f"tokens={diag['input_tokens']}+{diag['output_tokens']} "
                    f"calls={diag['llm_calls']} tools={diag['tool_calls']} "
                    f"attempts={diag['attempts']} {diag['duration_s']}s"
                )
                if diag.get("duplicate_of"):
                    print(f"    duplicate of: {diag['duplicate_of']}")
                if diag.get("reason"):
                    print(f"    reason: {str(diag['reason'])[:220]}")
                results.append(diag)
                if i + 1 < len(findings) and self.pace_seconds > 0:
                    time.sleep(self.pace_seconds)
        finally:
            if self.runtime is not None:
                try:
                    self.runtime.close()
                except Exception:
                    traceback.print_exc()
        counts = {
            "accepted": sum(1 for r in results if r["status"] == "accept"),
            "duplicates": sum(1 for r in results if r["status"] == "duplicate"),
            "rejected": sum(1 for r in results if r["status"] == "reject"),
            "model_errors": sum(1 for r in results if r["status"] == "model_error"),
        }
        self.summary = {
            "run_id": self.run_id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
            "duration_s": round(time.time() - t0, 1),
            "model_route": (
                "ollama local (qwen2.5:0.5b) via OpenMinion ollama provider"
                if self.provider == "ollama"
                else "groq (openai-compatible) via OpenMinion groq provider"
            ),
            "models": self.models,
            "counts": counts,
            "total_input_tokens": sum(r["input_tokens"] for r in results),
            "total_output_tokens": sum(r["output_tokens"] for r in results),
            "total_llm_calls": sum(r["llm_calls"] for r in results),
            "total_tool_calls": sum(r["tool_calls"] for r in results),
            "findings": results,
        }
        return self.summary
