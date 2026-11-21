# No rate limiting on login attempts

- **Severity:** High
- **Confidence:** 0.95
- **Status:** accept
- **Target:** https://example-shop.test/login
- **Source:** /home/hatch/workspace/dorahacks-cortensor-2418/findings_sample/05-no-rate-limit-login.md

## Summary

The report demonstrates that 200 consecutive failed login attempts from a single IP were processed without any block, throttle, lockout, or CAPTCHA challenge, indicating the login endpoint lacks any rate limiting or brute‑force mitigation. This allows an attacker to repeatedly guess passwords, potentially leading to credential compromise, which constitutes a high‑severity security issue.

## Evidence (raw finding)

# No rate limiting on login attempts

Target: https://example-shop.test/login

I sent 200 failed login attempts for the same account in under a minute from
one IP and never got blocked, throttled, or CAPTCHA-challenged. An attacker
can brute-force passwords indefinitely. Login endpoint, no lockout, no
rate limit, no CAPTCHA after failures.

## Suggested fix

Fix the root cause described above, re-test the exact repro, and re-run the checks that produced this finding before closing it.

---
_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval required before filing anywhere._
