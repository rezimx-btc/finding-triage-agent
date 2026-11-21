# Error page leaks stack trace with file paths

- **Severity:** Medium
- **Confidence:** 0.80
- **Status:** accept
- **Target:** https://example-shop.test/checkout
- **Source:** /home/hatch/workspace/dorahacks-cortensor-2418/findings_sample/06-stack-trace-leak.md

## Summary

The finding identifies a concrete, reproducible issue: error responses on https://example-shop.test/checkout include full stack traces with internal file paths and library versions, which aids attackers in mapping the tech stack and crafting targeted exploits. No sensitive data or credentials are exposed, and there is no direct data exfiltration, so this is not Critical/High, but it is a classic information-disclosure weakness (CWE-209) that meaningfully lowers the bar for follow-on attacks — Medium is appropriate. No past similar verdicts exist, so it is not a duplicate.

## Evidence (raw finding)

# Error page leaks stack trace with file paths

Target: https://example-shop.test/checkout

Triggering an error on the checkout page returns a full stack trace in the
response, including internal file paths and library versions. No sensitive
data or credentials in the trace, but it helps an attacker map the stack.
Verbose error, internal paths disclosed.

## Suggested fix

Fix the root cause described above, re-test the exact repro, and re-run the checks that produced this finding before closing it.

---
_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval required before filing anywhere._
