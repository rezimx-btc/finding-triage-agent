# DESIGN.md — Finding Triage Agent (OpenMinion)

**Event:** Cortensor Hackathon #5 (DoraHacks, Cortensor Mainnet Full Alpha)
**Team:** rezimx-btc (solo)
**Window:** 16 Oct–18 Dec 2026 · **Submission deadline:** 19 Dec 2026, 14:59 WIB
  (page: 2026-10-16T07:00Z to 2026-12-19T07:59Z)
**Prizes:** $1,150 total in $COR (1st $500 · 2nd $300 · 3rd $200 · 4th $100 · 5th $50;
  50% liquid upfront, 50% one-month staking lock). Awards are discretionary.
**Status:** RESEARCH + DESIGN (21 Nov). Build starts now.

---

## 1. The problem

A security researcher running bug-bounty hunts drowns in raw findings: scanner
output, half-formed notes, duplicate reports of the same bug in different words,
and no record of what was already triaged. Deciding what is real, what is a
duplicate, and what is worth writing up eats the hours that should go to hunting.
Existing triage is either a spreadsheet (no memory) or a black-box chatbot (no
audit trail, no reproducible verdict).

## 2. The concept — Finding Triage Agent

**One line:** *Feed it raw security findings; it deduplicates, severity-scores,
and drafts a structured report for each — and remembers every verdict, so the
same bug is never triaged twice.*

A small, working OpenMinion 0.1 agent that runs one useful, repeatable workflow:
**triage a batch of raw findings into judged, de-duplicated, report-ready items.**

Workflow (one run, repeatable):
1. **Ingest** — read raw findings from a folder of markdown/JSON notes.
2. **Deduplicate** — compare each finding against the session memory of past
   verdicts (same root cause in different words = duplicate, with a link to the
   original).
3. **Score** — severity (Critical/High/Medium/Low/Info) + confidence, with a
   one-paragraph reason citing the evidence in the finding.
4. **Draft** — a structured report per accepted finding (title, severity,
   repro steps, impact, suggested fix) in the format the researcher files.
5. **Remember** — every verdict is stored in session memory; the next run
   consults it first.
6. **Report** — a run summary (accepted / duplicates / rejected, with reasons)
   printed to the terminal and saved as JSON.

Human approval stays in the loop: nothing is filed anywhere; the agent drafts,
the researcher decides. That is the point — a triage agent, not an auto-submitter.

### Why this concept

- **Working functionality + useful outcome (25%)** — a real workflow from the
  builder's own daily work, with visible output every run.
- **Meaningful OpenMinion SDK usage (20%)** — agent execution, tools, sessions,
  memory, tasks, delegation (a sub-task per finding), diagnostics. The agent is
  built ON OpenMinion, not around it.
- **Reproducibility + demo (20%)** — deterministic test fixtures (a folder of
  sample findings with known verdicts), one command to run, demo video 1–5 min.
- **Building-block findings (25%)** — the heaviest-weighted criterion after
  functionality: a written note on what worked, what broke, and what should
  improve, based on real use. This is where the entry earns its keep.
- **Relevance (10%)** — a builder-workflow tool, exactly what the event asks for.

## 3. Architecture

```
findings/ (raw notes, .md/.json) ──┐
                                   ▼
                  TriageAgent (Python, OpenMinion 0.1)
                  ├── session: one session per triage run (memory persists
                  │   across runs in a local session store)
                  ├── tools:
                  │   ├── read_finding   (read + parse a raw finding file)
                  │   ├── recall_verdicts (search session memory for same
                  │   │   root cause / same target / same pattern)
                  │   ├── score_finding (model-backed severity + confidence
                  │   │   + reason; tool use is logged)
                  │   └── draft_report  (write the structured report file)
                  ├── tasks: one delegated sub-task per finding (fan out,
                  │   then collect), each with its own diagnostic trace
                  └── permissions: read-only on inputs; writes ONLY to
                      reports/ + memory store (declared + logged)
                                   ▼
                  reports/ (one .md per accepted finding)
                  run-summary.json (accepted / duplicates / rejected)
```

**Model route (decide by testing, in this order):**
1. **Groq via OpenAI-compatible endpoint** — the connected Groq account exists;
   check whether OpenMinion 0.1 accepts an OpenAI-compatible base URL + key,
   and read the Groq connector doc for how to call it. Key server-side/env only,
   never in the repo. If it works, this is the model for the demo.
2. **Ollama local tiny model** — free, no key; only if the VM can run it
   (small model, slow is fine for a demo).
3. **Document honestly** whichever route is used, including latency and failures.
   Never fake a model-backed run. Portal/Gemma4 access is NOT available and is
   explicitly not required for the core score — do not chase it.

**OpenMinion usage (must be real, not decorative):**
- SDK from the official repo (`github.com/OpenMinion/openminion`, PyPI
  `openminion` 0.1.x) — install from PyPI, pin the version in requirements.
- Exercise and report on: agent execution, model calls, tools, permissions,
  sessions, memory, tasks, delegation, diagnostics. The "Building Blocks Tested"
  note lists each with worked / broke / rough-edge.

## 4. Submission checklist (from the event page)

- Public source repo + README with setup and run instructions.
- Short explanation of the OpenMinion SDK workflow.
- One working example + **1–5 minute demo video**.
- **Building Blocks Tested** note: what was used, what worked, what did not.
- **What We Learned** note with actionable product feedback.
- Submit as a **PR linking the public project to the dedicated Hackathon #5
  repository** — ⚠️ the repository URL is STILL "to be added" on both the
  DoraHacks page and the Cortensor docs (last checked 21 Nov). The builder
  builds the repo; the coordinator/parent resolves the PR target before
  submission (likely via Cortensor Discord). Do NOT invent a repo URL.
- Repo name (public, `rezimx-btc/`): `finding-triage-agent` (confirm at build time).

## 5. Repo plan

```
dorahacks-cortensor-2418/
├── DESIGN.md            ← this file
├── README.md            ← problem, workflow, setup, run, model route
├── LICENSE              ← MIT
├── requirements.txt     ← openminion==0.1.x (pinned), no other heavy deps
├── triage_agent/        ← agent, tools, session/memory store, report writer
├── findings_sample/     ← deterministic fixtures (10 findings, known verdicts)
├── reports/             ← generated (gitignored sample output kept for demo)
├── tests/               ← dedup + scoring unit tests (must pass)
├── BUILDING_BLOCKS.md   ← what was used, worked / broke / rough edges
├── WHAT_WE_LEARNED.md   ← actionable product feedback
└── docs/                ← demo script, screenshots, terminal transcript
```

## 6. Risks + open questions

1. **Model route is the biggest unknown** — OpenMinion's provider options must
   be tested first; if no model route works, the agent cannot be "model-backed"
   and the entry fails its core requirement. Test this FIRST, before building
   the workflow.
2. **Submission PR target repo unknown** — see §4; resolve before 19 Dec.
3. **Demo video (1–5 min)** — the builder produces a scripted terminal demo +
   screenshots/transcript; video assembly is a later (parent) step.
4. **Cortensor may require identity checks for prizes** — a user step if we win;
   note it, don't pre-empt it.
5. **Awards are discretionary** — meeting requirements does not guarantee a
   prize; the entry must still be genuinely good, not merely compliant.
