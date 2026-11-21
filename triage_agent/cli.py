"""Finding Triage Agent — CLI.

Usage (from the repo root, inside the venv)::

    python -m triage_agent.cli [--findings findings_sample] [--limit 3] [--fresh]

Environment: GROQ_API_KEY must be set, or run on the Muse VM where the
custom.groq connector can issue a fresh surrogate (see agent.resolve_groq_key).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Proxy-env fix must happen before openminion/httpx import (see agent.py).
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Finding Triage Agent (OpenMinion 0.1)")
    parser.add_argument("--findings", default="findings_sample", help="folder of raw findings")
    parser.add_argument("--reports", default="reports", help="folder for draft reports")
    parser.add_argument("--store", default="triage_agent/memory_store.json", help="verdict memory file")
    parser.add_argument("--summary", default="run-summary.json", help="run summary JSON path")
    parser.add_argument("--limit", type=int, default=None, help="triage only the first N findings")
    parser.add_argument("--fresh", action="store_true", help="wipe the verdict memory before the run")
    parser.add_argument("--pace", type=float, default=25.0, help="seconds between findings (Groq TPM pacing)")
    parser.add_argument(
        "--provider",
        choices=["groq", "ollama"],
        default="groq",
        help="model provider (groq = Groq cloud, ollama = local model, no key)",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="explicit OpenMinion config file (default: ./.openminion/agents.json)",
    )
    args = parser.parse_args()

    root = Path.cwd()
    store_path = root / args.store
    if args.fresh and store_path.exists():
        store_path.unlink()
        print(f"[triage] memory wiped: {store_path}")

    models = ["qwen2.5:0.5b"] if args.provider == "ollama" else None
    config_path = args.config_path
    if config_path is None and args.provider == "ollama":
        config_path = ".openminion/agents-ollama.json"
    agent = TriageAgent(
        findings_dir=root / args.findings,
        reports_dir=root / args.reports,
        store_path=store_path,
        project_root=root,
        pace_seconds=args.pace,
        models=models,
        provider=args.provider,
        config_path=config_path,
    )
    summary = agent.run(limit=args.limit)
    out = root / args.summary
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\n================ RUN SUMMARY ================")
    print(json.dumps({k: v for k, v in summary.items() if k != "findings"}, indent=2))
    for r in summary["findings"]:
        print(
            f"  {r['finding_id']:>12}  {r['status']:<10} {r.get('severity') or '-':<8} "
            f"conf={r.get('confidence', 0):.2f} model={r['model'].split('/')[-1]} "
            f"attempts={r['attempts']}"
        )
    print(f"summary saved: {out}")
    return 0 if summary["counts"]["model_errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
