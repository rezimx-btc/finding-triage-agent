# Finding Triage Agent

**Cortensor Hackathon #5 (DoraHacks) — built with the OpenMinion 0.1 Python SDK.**

Feed it raw security findings; it deduplicates, severity-scores, and drafts a
structured report for each — and remembers every verdict, so the same bug is
never triaged twice.

```
findings/ (raw .md/.json notes)
        │
        ▼
TriageAgent (OpenMinion 0.1)
  ├── one delegated agent run per finding (shared APIRuntime)
  ├── tools: recall_verdicts · record_verdict · draft_report
  │   (read_finding available for re-reads; ingest is deterministic)
  ├── session memory: verdicts persist in triage_agent/memory_store.json
  │   and in the OpenMinion session store (.openminion/state)
  └── permissions: read-only on inputs; writes only to reports/ + memory
        │
        ▼
reports/ (one .md per accepted finding) + run-summary.json
```

Human approval stays in the loop: nothing is filed anywhere; the agent
drafts, the researcher decides.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # openminion==0.1.19

# 1) Configure OpenMinion (Groq provider, no key in the file)
openminion config init --provider groq
#    then set providers.groq.model to openai/gpt-oss-120b
#    (the bundled .openminion/agents.json already does this)

# 2) Set the model key (env var only -- never commit a key)
export GROQ_API_KEY="gsk_..."

# 3) Run the demo (10 deterministic sample findings)
python -m triage_agent.cli --fresh

# Short version for a video recording (first 3 findings):
bash docs/demo.sh
```

No key? Run fully local with Ollama (free, no key, slower on CPU):

```bash
ollama serve & ollama pull qwen2.5:0.5b
python -m triage_agent.cli --fresh --provider ollama --limit 3
```

See [BUILDING_BLOCKS.md](BUILDING_BLOCKS.md) for what the Ollama route can and
cannot do (the 0.5B model cannot reliably emit the structured verdict JSON
OpenMinion validates -- Groq is the recommended route).

## How a run works

1. **Ingest** — read raw findings from a folder of markdown/JSON notes.
2. **Deduplicate** — each finding is checked against session memory of past
   verdicts (deterministic token-overlap recall + the model's duplicate call,
   linked to the original finding).
3. **Score** — severity (Critical/High/Medium/Low/Info) + confidence +
   one-paragraph reason citing the evidence. The judgement is the model's,
   captured as structured `record_verdict` tool arguments (validated: enum +
   ranges) or as the run's validated structured output. A finding the model
   cannot judge is reported as `model_error` -- never invented.
4. **Draft** — a structured report per accepted finding
   (title, severity, repro/evidence, impact, suggested fix).
5. **Remember** — every verdict is stored in session memory before the next
   finding; a second run over the same folder marks everything a duplicate.
6. **Report** — run summary printed + saved as `run-summary.json`
   (accepted / duplicates / rejected / model_errors, with per-finding
   diagnostics: tokens, LLM calls, tool calls, attempts, model, duration).

## Tests

```bash
python -m unittest discover -s tests -v   # 20 tests, stdlib only
```

Covers the deterministic parts: dedup recall scoring, verdict validation,
finding parsing, report rendering. The model's judgement is non-deterministic
and is not asserted -- the demo reports the model's verdicts against the
fixtures' expected verdicts instead (see `tests/test_triage.py::EXPECTED`).

## Demo results (21 Nov 2026, run `96d516f91a93`, Groq route, transcript in `docs/demo-transcript.txt`)

10/10 findings triaged, **0 model_errors**, 488.7 s total:

| Finding | Model verdict | Fixture expected | Match |
|---|---|---|---|
| 01 XSS login | accept High 0.95 | accept High | yes |
| 02 XSS duplicate | duplicate of 01, 0.95 | duplicate of 01 | yes |
| 03 SQLi search | accept Critical 0.96 | accept Critical | yes |
| 04 SQLi duplicate | duplicate of 03, 0.90 | duplicate of 03 | yes |
| 05 no rate limit | accept **High** 0.95 | accept Medium | severity differs |
| 06 stack-trace leak | accept **Medium** 0.80 | accept Low | severity differs |
| 07 outdated jQuery | **reject** 0.95 | accept Info | status differs |
| 08 CSRF password | accept High 0.92 | accept High | yes |
| 09 open redirect | accept Medium 0.95 | accept Medium | yes |
| 10 vague report | reject 0.90 | reject | yes |

7/10 match the fixture labels exactly; the 3 differences are genuine
judgement calls (the model's reasons cite the evidence -- e.g. 07 was
rejected because no reachable exploit path was shown). Every verdict was
recovered via `record_verdict` after its run's finalize turn hit a Groq
429 (`verdict_source: "record_verdict tool (finalize failed)"`). Token
stats read 0 in `run-summary.json` because OpenMinion only returns stats
on a clean run return -- a diagnostics gap, see BUILDING_BLOCKS.md §3.

## Model route

| Route | Status (21 Nov 2026, tested live) |
|---|---|
| Groq `openai/gpt-oss-120b` + `qwen/qwen3.8-27b` via OpenMinion's native `groq` provider | **Works, recommended.** Free tier 8,000 TPM/model; the agent rotates models and waits for TPM headroom (see `triage_agent/agent.py::wait_for_headroom`). Verdicts are durable the moment `record_verdict` executes, so a rate-limited finalize turn cannot lose them. |
| Groq `openai/gpt-oss-20b` | Works, but its **daily budget (200k TPD) was exhausted by shared org use on 21 Nov 2026** (Used 199,582 at ~20:30 WIB) -- removed from the default rotation until the daily budget resets. |
| Ollama local `qwen2.5:0.5b` | Connects, but too weak for OpenMinion's structured-output validation and ~10 min/finding on CPU. Not recommended. |
| Cortensor Portal / Router | Not tested -- no Portal key available; explicitly out of scope for this entry (see DESIGN.md). |

## Layout

```
├── DESIGN.md               design (prose) this build follows
├── README.md               this file
├── LICENSE                 MIT
├── requirements.txt        openminion==0.1.19
├── .openminion/
│   ├── agents.json         OpenMinion config (Groq provider, no secrets)
│   └── agents-ollama.json  OpenMinion config (Ollama provider, no secrets)
├── triage_agent/           agent, tools, memory store, CLI
├── findings_sample/        10 deterministic fixtures with known verdicts
├── reports/                generated draft reports (demo output)
├── tests/                  dedup + scoring unit tests
├── docs/
│   ├── run_demo.sh         full demo (10 findings, transcript to docs/)
│   ├── demo.sh             short video demo (3 findings)
│   └── demo-transcript.txt terminal transcript of the full demo
├── BUILDING_BLOCKS.md      what was used, what worked / broke / rough edges
└── WHAT_WE_LEARNED.md      actionable product feedback for OpenMinion
```

## Notes

- No funds, no mainnet, no paid services. Groq free tier only; Ollama is
  free and local. Nothing here touches Aevum or any chain.
- `GROQ_API_KEY` stays in the environment. The repo contains no keys; see
  BUILDING_BLOCKS.md for the `.openminion/` audit (only the two config files
  are committed; all runtime state is gitignored).
- Submission: PR to the Hackathon #5 repository (URL still "to be added" on
  the DoraHacks page as of 21 Nov 2026 -- see DESIGN.md §4).

## Demo video

- `video/finding-triage-demo.mp4` (1280x720, 1:50, H.264, sha256
  `2e9615e60745ee06e86d4dd23fc07516734d6ebd7bcd6a109e3247c87785a5a6`).
- Recorded live 21 Nov 2026: `bash docs/demo.sh` under `script -T`
  (run `f1b677df1086`, 3 findings, accepted 2 / duplicates 1 / model_errors 0).
  Rendered with `docs/render-demo-video.py` from the typescript capture;
  only the idle waits while the model thinks are time-compressed (cap 12 s),
  the terminal text itself is verbatim real output of that run.
- The full 10-finding run (run `96d516f91a93`, accepted 6 / duplicates 2 /
  rejected 2 / model_errors 0) is in `docs/demo-transcript.txt`.
