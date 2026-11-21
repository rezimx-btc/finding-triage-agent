# What We Learned — feedback for OpenMinion (from building this entry)

Built 21 Nov 2026 with OpenMinion 0.1.19. Each item is something I hit
while building, with the concrete change that would have helped.

## 1. Give the decide loop a prompt budget (highest value)
The default decide-phase prompt (~8,600 tokens with 8 built-in tools and
a 16.5 KB task-context block) exceeds Groq's entire free-tier TPM budget
(8,000) on its own. I only found this by putting a logging proxy between
the SDK and Groq. **Ask:** a "lean mode" config (fewer built-in entry
tools, shorter task-context block) and a documented per-call token
estimate -- or a `dry-run` that prints the decide prompt's token count
before the first real call.

## 2. Honor `Retry-After` / 429 backoff in the provider transport
On a 429 the SDK retried the same request immediately, 3-9 times, even
when Groq said "try again in 31s" -- and after a failed `submit_output`
it re-sent a *bigger* recovery prompt into the same depleted budget.
**Ask:** exponential backoff honoring the provider's retry hint, and
never grow the recovery prompt when the failure was a quota error.

## 3. Update the Groq default model
`openminion config init --provider groq` writes
`llama-3.3-70b-versatile`, which left Groq's free/Developer plans in
August 2026. A first-time user follows the quick-start and gets an
opaque provider error. **Ask:** default to `openai/gpt-oss-120b` (and
note that `gpt-oss-20b`'s 200k/day free budget is the first to exhaust
on a shared org -- see BUILDING_BLOCKS.md §2.5), and validate the
configured model against the provider's model list at setup time (the
SDK already lists providers; a `--check-provider` model check would
catch this).

## 4. Tell the model the `submit_output` domain enum (or default it)
The finalize call fails with a 400 when the model invents a `domain`
value (`"security"` is the obvious guess; the enum has no such member).
The retry guidance never lists the allowed values. **Ask:** include the
enum in the tool description, or default a missing/invalid domain to
`general` server-side instead of failing the whole turn.

## 5. Document the two non-obvious setup requirements in the Python quick-start
(a) A config file is mandatory (`Agent.run` without
`./.openminion/agents.json` raises `ConfigManagerError`); the embedded
Python snippet does not mention `config init`. (b) Tool calls block on
an interactive approval prompt unless `approval_callback` is supplied.
**Ask:** one copy-pasteable Python quick-start that includes config init
+ `approval_callback`.

## 6. Make `subagent()` tool inheritance explicit
`subagent(parent, tools=[names])` takes tool *names*; it was never clear
whether those resolve against the parent's registered `@tool` functions,
and my probes produced zero tool calls from the child. **Ask:** a doc +
example showing a parent-owned `@tool` function actually executing
inside a `subagent`, or an explicit error when a name does not resolve.

## 7. Don't let `trust_env` proxies crash provider calls
`httpx.Client(trust_env=True)` crashes on `NO_PROXY` values containing
bracketed IPv6 entries (`[::1]`), which is a common VM/container
default. **Ask:** sanitize `NO_PROXY` entries the URL parser rejects,
or set `trust_env=False` for provider clients and document proxy setup
explicitly.

## 8. Expose per-call token usage in run stats
`AgentRunResult.stats` gives totals per run. Budgeting against an 8k
TPM cap needs per-call numbers (decide vs finalize vs recovery).
**Ask:** a per-call breakdown (tokens + latency + retry count) in stats
or in the diagnostics output.

## 9. A structured-output fallback for small models
`qwen2.5:0.5b` (Ollama) could not emit the validated `TriageVerdict`
JSON at all (3/3 attempts, prose instead). The validation error helpfully
includes the raw reply. **Ask:** an opt-in "text fallback" hook that lets
the caller parse the raw reply when schema validation fails, instead of
failing the turn -- small local models would become usable for simple
schemas.

## 10. Keep the good parts
What genuinely worked and should not change: the `Agent` / `APIRuntime`
embedding shape is small and readable; `@tool` + `forced_tools` +
`approval_callback` compose well; `output_type` validation errors
include the raw reply; `setup --list-providers` is the fastest way to
see the provider matrix; session persistence in sqlite just works.
