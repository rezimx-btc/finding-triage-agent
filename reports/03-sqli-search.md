# SQL injection in product search

- **Severity:** Critical
- **Confidence:** 0.96
- **Status:** accept
- **Target:** https://example-shop.test/search?q=
- **Source:** /home/hatch/workspace/dorahacks-cortensor-2418/findings_sample/03-sqli-search.json

## Summary

The finding provides concrete evidence of an exploitable SQL injection: the `q` parameter of https://example-shop.test/search?q= is concatenated directly into a SQL query. The supplied payloads (`' OR '1'='1` and `' UNION SELECT username,password FROM users--`) successfully return all products and dump the users table with password hashes, demonstrating full database read. This demonstrates a clear vulnerability with high impact, justifying a Critical severity.

## Evidence (raw finding)

The search parameter q is concatenated directly into a SQL query. Payload: ' OR '1'='1 returns all products. Payload: ' UNION SELECT username,password FROM users-- dumps the users table including password hashes. Search endpoint, q parameter, unsanitized SQL concatenation, full database read.

## Suggested fix

Fix the root cause described above, re-test the exact repro, and re-run the checks that produced this finding before closing it.

---
_Drafted by Finding Triage Agent (OpenMinion 0.1). Human approval required before filing anywhere._
