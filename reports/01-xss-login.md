# Reflected XSS in login error page

- **Severity:** High
- **Confidence:** 0.95
- **Status:** accept
- **Target:** https://example-shop.test/login
- **Source:** /home/hatch/workspace/dorahacks-cortensor-2418/findings_sample/01-xss-login.md

## Summary

The finding includes reproducible steps: submitting the payload `<script>alert(1)</script>` as the username causes the login error page to reflect the input without encoding, resulting in script execution in the victim's browser. This demonstrates a reflected XSS that can be used to steal session cookies, providing clear evidence of a high‑severity issue.

## Evidence (raw finding)

# Reflected XSS in login error page

Target: https://example-shop.test/login

Steps:
1. Go to the login page and submit username `<script>alert(1)</script>` with any password.
2. The error page reflects the submitted username inside the HTML without encoding.
3. The script executes in the victim's browser.

Impact: an attacker can craft a login link that runs JavaScript in a victim's
session and steal the session cookie. Reflected input, no encoding, error page.

## Suggested fix

Fix the root cause described above, re-test the exact repro, and re-run the checks that produced this finding before closing it.

---
_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval required before filing anywhere._
