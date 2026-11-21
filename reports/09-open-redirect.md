# Open redirect via next parameter after login

- **Severity:** Medium
- **Confidence:** 0.95
- **Status:** accept
- **Target:** https://example-shop.test/login?next=
- **Source:** /home/hatch/workspace/dorahacks-cortensor-2418/findings_sample/09-open-redirect.md

## Summary

The finding provides concrete evidence of an open redirect vulnerability: the login page redirects to any URL supplied in the `next` parameter without allowlist validation. An attacker can craft a link such as `?next=https://evil.example/phish` to redirect authenticated users to a malicious site, enabling phishing attacks. While no session token or credentials are leaked directly by the redirect, the ability to deceive users into visiting malicious sites constitutes a medium‑severity impact. The description is clear and reproducible, giving high confidence in the finding.

## Evidence (raw finding)

# Open redirect via next parameter after login

Target: https://example-shop.test/login?next=

After login the site redirects to whatever URL is in the `next` parameter
with no allowlist check. `?next=https://evil.example/phish` sends the user
to an attacker page. Useful for phishing, but no token or session is leaked
by the redirect itself. Open redirect, unvalidated next parameter.

## Suggested fix

Fix the root cause described above, re-test the exact repro, and re-run the checks that produced this finding before closing it.

---
_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval required before filing anywhere._
