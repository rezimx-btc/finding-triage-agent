# Building Blocks Tested — Finding Triage Agent (OpenMinion 0.1.19)

Tested live on 21 Nov 2026, Python 3.12, `openminion==0.1.19` from PyPI.
Everything below was run, not read about. Where something failed, the
failure is stated with the evidence (request sizes, Groq error bodies,
token counts) instead of smoothed over.

## What was used (really)

| Block | How it is used in this repo |
|---|---|
| `Agent` + `APIRuntime` | One shared `APIRuntime` (project config `./.openminion/agents.json`); one `Agent` execution per finding, each with its own `session_id` (`triage-<run>-<finding>-a<attempt>`) |
| `openminion.tool` | `record_verdict` (forced -- the model-backed judgement, validated + persisted by the tool). `recall_verdicts` and `draft_report` are real `@tool` functions in `triage_agent/tools.py` (unit-tested); recall is computed deterministically by the orchestrator and embedded in the run message instead of costing a model turn (see §2.6), and reports are written by the orchestrator from the stored verdict |
| `forced_tools` | `["record_verdict"]` -- the model must capture its judgement as structured tool arguments |
| `output_type` (pydantic) | `TriageVerdict` structured final output, validated by the runtime; fallback capture path when the tool call path fails |
| `approval_callback` | Allowlist: only our 4 tools auto-allowed; anything else denied + logged (permissions, enforced in code) |
| `ProviderError` | Caught and classified (`RATE_LIMITED` -> backoff + model rotation); **a verdict already recorded via `record_verdict` is recovered even when the finalize turn fails** (`triage_one` checks the store in the exception path) |
| `AgentRunResult.stats` | Per-finding diagnostics: `input_tokens`, `output_tokens`, `llm_calls`, `tool_calls`, `duration_ms` -- printed and saved in `run-summary.json` (stats are 0 when the run raises before returning, even if the verdict was recovered -- a diagnostics gap, see §3) |
| Sessions | `session_id` per run; messages verified persisted in `.openminion/state/openminion.db` (`messages` table) |
| Memory | Verdicts persist in `triage_agent/memory_store.json` (the agent's session memory, consulted first on every run) **plus** the OpenMinion session store. The OpenMinion memory module's programmatic API (`MemoryBundle`) was **not** used -- see §3 |
| Tasks / delegation | One delegated sub-task per finding: the orchestrator fans out to one scorer agent run per finding, then collects results into the run summary. Implemented with direct `Agent` runs sharing one runtime (see §2, subagent note) |
| Providers | `groq` (native, OpenAI-compatible) and `ollama` (native, local) |
| CLI | `openminion config init --provider groq`, `openminion setup --list-providers` |

## 1. What worked

- **Groq via the native `groq` provider.** `GROQ_API_KEY` from env,
  endpoint `https://api.groq.com/openai/v1`, models `openai/gpt-oss-20b`
  and `openai/gpt-oss-120b`. A direct small prompt answers in ~2 s.
  With explicit tools, the model calls `recall_verdicts` with correct
  arguments and the approval callback fires (verified in probe runs).
- **Forced tools + approval callback.** `forced_tools=["recall_verdicts"]`
  reliably produces the memory-check call first; the callback receives
  `(name, args, reason)` and can allow/deny per tool.
- **Structured output validation.** `output_type=TriageVerdict` validates;
  on invalid JSON the error includes the raw reply (good for debugging).
- **Session persistence.** Inbound messages land in the sqlite session
  store; re-running with the same session id resumes that thread.
- **Ollama provider connects.** `ollama serve` + `qwen2.5:0.5b` answers
  through the OpenMinion ollama provider (no key, no TPM).
- **TPM headroom probe.** Groq returns `x-ratelimit-remaining-tokens` on
  chat completions; a 1-token probe reads the live budget
  (`triage_agent/agent.py::groq_remaining_tokens`).

## 2. What broke (with evidence)

### 2.1 Bare-Agent decide prompt exceeds Groq free TPM (413)
A bare `Agent` (no tools) sends a decide-phase request of **~43 KB /
~8,600-9,100 tokens**: a 16.5 KB system block (task-context instructions
with the full `TaskContextUpdate` JSON schema merged into every entry
tool) plus 8 built-in entry tools (`tool.request`, `respond`, `coding`,
`plan`, `research`, `decompose`, `clarify`, `review.diff`). Groq free
tier is **8,000 TPM**, so Groq answers:
`413 Request too large ... Limit 8000, Requested 8753`.
**Fix that worked:** pass explicit tools -- the decide request shrank to
~11-12 KB (~2,900 tokens) and fits. There is no config flag to slim the
built-in prompt that I could find.

### 2.2 Shared-org TPM congestion + no Retry-After honoring (429)
Groq's 8,000 TPM is per model **per organization**, and this org is
shared. Measured mid-run: `Used 5497` before my first call, `Used 7397`
on a 994-token finalize call. A clean triage run costs ~3,900 tokens
(decide ~2,900 + finalize ~1,000), so it only fits when the minute is
quiet. OpenMinion retries 429s **immediately** (observed 3-9 instant
retries of the same request) even when Groq says `try again in 31s`,
and after a failed `submit_output` it re-issues a **much bigger**
decide request (18 KB, 7 messages, ~4,700 tokens) that can never fit a
depleted budget. **Mitigation in this repo:** TPM headroom gate
(wait until `remaining >= 7000`), model rotation (20b <-> 120b),
retry-with-headroom in the orchestrator. It makes runs succeed
eventually, not reliably on the first attempt.

### 2.3 `submit_output` domain-enum 400
The model's finalize call repeatedly fails with:
`400 Tool call validation failed: ... /domain: value must be one of
'general', 'finance', 'news', 'weather', 'regulation', 'shopping',
'sports', 'other'`. The model evidently sends something like
`"security"`. The retry guidance does not list the allowed values.
**Mitigation attempted:** the scorer instructions now say to set
`domain` to `'general'` in the final answer. The 400 self-heals on
retry (the model picks a valid value eventually), but each failure
triggers the oversized re-decide in §2.2.

### 2.4 `qwen/qwen3.8-27b` (Groq): malformed envelope via `subagent()` only
One run through `subagent()` produced `UNEXECUTABLE_TOOL_ENVELOPE: The
model generated a tool envelope that could not be executed` and
`tool_calls: 0`. The same model through a direct `Agent` run with a
forced tool called `record_verdict` cleanly (verified in the demo run:
finding 02, duplicate of 01, conf 0.95). The envelope failure looks
specific to the subagent path, not the model. Qwen **is** in this repo's
model rotation (with gpt-oss-120b).

### 2.5 TPD exhaustion is a separate, invisible budget (found 21 Nov ~20:30 WIB)
After hours of TPM debugging, `gpt-oss-20b` started failing with
`tokens per day (TPD): Limit 200000, Used 199582, Requested 3335` --
**418 daily tokens left**, while the TPM probe still showed 7,927
remaining. Tiny prompts still worked; any real request did not. Groq
does not expose remaining TPD in response headers, so the orchestrator
cannot gate on it -- only the error body reveals it. 120b and qwen
accepted the same 3.3k-token probe. **Consequence:** 20b was removed
from the default rotation (it recovers at the UTC day boundary).

### 2.6 Lean run: verdict durable at record time (the fix that made the demo work)
A full triage run needs 2-3 sequential LLM calls (~4-5.5k tokens), and
any one of them can 429 on a shared org. Two changes made the demo
robust: (a) dedup recall moved out of the model turn -- the orchestrator
computes it deterministically and embeds the matches in the message, so
the run is decide (forced `record_verdict`) + finalize; (b) the verdict
is durable the moment `record_verdict` executes, and the orchestrator
recovers it from the store even when the finalize turn 429s
(`verdict_source: "record_verdict tool (finalize failed)"`). With these,
findings 01 and 02 both landed first-attempt with the expected verdicts
(accept High 0.95; duplicate of 01, 0.95) despite the finalize 429s.

### 2.7 `subagent()` tool wiring unconfirmed
`subagent(parent, tools=["score_finding"])` (names only) never produced
a tool call in my probes (`tool_calls: 0` in the two runs that got far
enough; a third 429'd first). It is unclear whether name-allowlisted
tools resolve against the parent's registered `@tool` functions.
**Consequence:** this repo implements delegation as one direct `Agent`
run per finding sharing a single `APIRuntime` (fan-out in the
orchestrator), not via `subagent()`. `Handoff` was read but not used.

### 2.8 Ollama `qwen2.5:0.5b`: too weak for the loop
Connects and answers, but 3/3 attempts failed `AgentOutputValidationError`
(the model replies in prose instead of the `TriageVerdict` JSON), and one
finding took **~10 minutes** on this 4-CPU VM. A 0.5B model is below the
bar for OpenMinion's structured-output + tool loop. Not recommended;
kept as a documented `--provider ollama` fallback only.

### 2.9 Config file is mandatory, and its Groq default is dead
`Agent.run` without `./.openminion/agents.json` raises
`ConfigManagerError: config file not found`. And `openminion config init
--provider groq` writes default model `llama-3.3-70b-versatile`, which
left Groq's free/Developer plans on 16 Aug 2026 (enterprise-only now).
You must override the model to `openai/gpt-oss-20b` (this repo's bundled
config already does).

### 2.10 httpx `NO_PROXY` crash (environment quirk, OpenMinion-adjacent)
OpenMinion's provider transport builds `httpx.Client(trust_env=True)`.
This VM's `NO_PROXY` contains bracketed IPv6 entries (`[::1]`,
`[fd8b:...]`), which httpx cannot parse:
`InvalidURL: Invalid port: ':1]'`. Every provider call failed until
`NO_PROXY` was narrowed to `localhost,127.0.0.1` (the agent does this
itself on import; see `triage_agent/agent.py`). urllib-based clients are
unaffected, which is why the Groq connector helper worked while
OpenMinion did not.

### 2.11 Interactive approval blocks scripts
Without `approval_callback`, a tool call stops at a console prompt
(`Reply exactly yes or allow_once ...`). In a non-interactive run that
is a hang, not a denial. The callback is the way; the Python quick-start
should show it.

## 3. Rough edges / not verified

- **Memory module API not exercised.** Verdict memory is this repo's own
  JSON store; I did not get `MemoryBundle` / the memory module's
  programmatic surface into the loop in the time available. Sessions
  (message persistence) are verified; the memory *module* is not.
- **Handoff delegation not exercised** (read only); see §2.7.
- **Cortensor providers not tested** (Portal/Router need a key this
  project does not have; explicitly out of scope per DESIGN.md).
- **Daemon / HTTP API / MCP surfaces not tested.**
- **Runtime boot is slow** (~10-30 s per `APIRuntime` creation); sharing
  one runtime across runs matters and is what this repo does.
- **Stats are totals only** (`input_tokens` etc. per run, no per-call
  breakdown) -- per-call token counts came from a local logging
  forwarder I ran during debugging, not from the SDK. Worse: when a
  run raises (e.g. finalize 429), stats are **0 even though the model
  did real work** -- in the 21 Nov demo all 10 verdicts were recovered
  from `record_verdict` but `run-summary.json` reports 0 tokens / 0
  calls. The SDK could attach partial stats to the raised error.
- **Reset-header parsing** in my own TPM probe: Groq's reset header
  format varies; parse defensively (a bug I introduced and fixed).
- **Ollama install friction on this VM** (not OpenMinion's fault, but
  relevant to "local-first" claims): no `zstd` (apt update hung), the
  1.5 GB tarball, and `/tmp` being a 512 MB tmpfs (first download died
  writing to it). Installed via `pip install zstandard` + streaming
  extract instead.
- **Full second-run dedup (model path) not executed.** Deterministic
  recall against the populated store is verified (02->01 at 0.28,
  04->03 at 0.35, 10->none) and the unit tests cover recall; a second
  full model run over the same folder was not run (Groq budget).

## 4. `.openminion/` audit (repo hygiene, re-verified 21 Nov 2026 ~21:50 WIB)

Only two files under `.openminion/` are committed:

- `agents.json` -- Groq provider config. **No secrets**: every
  provider's `api_key` field is `""`; keys come from env vars only.
- `agents-ollama.json` -- Ollama provider config. Same: no secrets.

Everything else under `.openminion/` is local runtime state and is
gitignored (`.openminion/*` except the two configs):

| Subdir | Contents | Commit? |
|---|---|---|
| `state/` | `openminion.db`, `brain/{sessions,brain,memory}.db` -- sessions, messages, run state | No -- runtime state |
| `telemetry/` | `telemetry.db` (~8 MB) -- run telemetry | No |
| `policy/` | `policy.db` + many `policy.db.bak/*.sqlite` snapshots (one per run) | No |
| `identity/` | local identity material | No |
| `memory/` | memory store DBs | No |
| `skill/`, `task/`, `ops/`, `retrieve/`, `artifact/`, `authored_tools/` | skill/task/job/retrieval/artifact/tool stores (sqlite) | No |
| `storage/`, `tool-runs/`, `session-context/`, `browser-playwright/` | empty on this machine | No (empty dirs) |

Secret scan over the whole repo (patterns: `privateKey`, `seed`,
`password =`, `hsurr:`, `gsk_`, `sk-...`, `BEGIN ... PRIVATE KEY`),
re-run 21 Nov 2026 ~21:50 WIB: no real secrets found. The only hits
are the word "password" inside the *fake demo findings* (e.g.
"password-change form"), the literal string `hsurr:` in a docstring
explaining the surrogate mechanism (no value attached), and `sk-`
inside ordinary words ("task-context"). `GROQ_API_KEY` is read from the
environment only. The two committed configs carry `api_key: ""` on all
7 provider entries each, and a strings-grep over all `.openminion/`
runtime DBs found no `gsk_` / `hsurr:` values.
