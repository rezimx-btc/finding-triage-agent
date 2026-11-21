# CSRF on password change form

- **Severity:** High
- **Confidence:** 0.92
- **Status:** accept
- **Target:** https://example-shop.test/account/password
- **Source:** /home/hatch/workspace/dorahacks-cortensor-2418/findings_sample/08-csrf-password-change.json

## Summary

Solid, reproducible finding on a concrete target (https://example-shop.test/account/password): the state-changing password POST lacks an anti-CSRF token, and the reporter provides working proof (a cross-origin form that auto-submits and successfully changes a logged-in victim's password). That combination — missing token, state-changing endpoint, confirmed exploitation leading to full account takeover — is a real CSRF vulnerability. I rate it High rather than Critical: a CSRF-based forced password change can be severe and give account takeover, but it requires the victim to be logged in with an active session and to visit the attacker page in that session, a slightly narrower window than unconditional RCE or mass data breach; impact severity (account takeover, data exfiltration of personal info and stored payment details if the shop holds them) supports High.

## Evidence (raw finding)

The password-change form has no anti-CSRF token. I built a page on another origin that auto-submits a POST to /account/password with a new password, and while logged in as the victim the password changed. Any site the victim visits can take over the account. Missing CSRF token, state-changing POST, full account takeover.

## Suggested fix

Fix the root cause described above, re-test the exact repro, and re-run the checks that produced this finding before closing it.

---
_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval required before filing anywhere._
