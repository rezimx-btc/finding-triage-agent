"""Unit tests for the Finding Triage Agent (stdlib unittest, no network).

Covers the deterministic parts: dedup recall scoring, verdict validation,
finding parsing, and report rendering. The model's judgement itself is
non-deterministic and is NOT asserted here -- the demo run reports the
model's verdicts against the fixtures' expected verdicts instead.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.memory_store import VerdictStore, overlap_score, recall_key, tokenize
from triage_agent.tools import parse_finding_file, render_report, validate_verdict

FIXTURES = Path(__file__).resolve().parent.parent / "findings_sample"

EXPECTED = {
    # finding_id -> (expected status, expected severity or "")
    "01-xss-login": ("accept", "High"),
    "02-xss-login-duplicate": ("duplicate", ""),
    "03-sqli-search": ("accept", "Critical"),
    "04-sqli-search-duplicate": ("duplicate", ""),
    "05-no-rate-limit-login": ("accept", "Medium"),
    "06-stack-trace-leak": ("accept", "Low"),
    "07-outdated-jquery": ("accept", "Info"),
    "08-csrf-password-change": ("accept", "High"),
    "09-open-redirect": ("accept", "Medium"),
    "10-vague-insecure": ("reject", ""),
}


class TestOverlap(unittest.TestCase):
    def test_identical_is_one(self):
        self.assertEqual(overlap_score("xss in login page", "xss in login page"), 1.0)

    def test_unrelated_is_low(self):
        self.assertLess(overlap_score("sql injection in search", "outdated jquery library"), 0.1)

    def test_reworded_duplicate_scores_high(self):
        a = parse_finding_file(FIXTURES / "01-xss-login.md")
        b = parse_finding_file(FIXTURES / "02-xss-login-duplicate.md")
        self.assertGreaterEqual(overlap_score(recall_key(a), recall_key(b)), 0.18)

    def test_reworded_sqli_duplicate_scores_high(self):
        a = parse_finding_file(FIXTURES / "03-sqli-search.json")
        b = parse_finding_file(FIXTURES / "04-sqli-search-duplicate.md")
        self.assertGreaterEqual(overlap_score(recall_key(a), recall_key(b)), 0.18)

    def test_different_login_findings_do_not_match(self):
        # 01 (XSS) and 05 (rate limit) share the login page but are different bugs.
        a = parse_finding_file(FIXTURES / "01-xss-login.md")
        b = parse_finding_file(FIXTURES / "05-no-rate-limit-login.md")
        self.assertLess(overlap_score(recall_key(a), recall_key(b)), 0.18)

    def test_tokenize_drops_stopwords(self):
        self.assertNotIn("the", tokenize("the quick brown fox"))
        self.assertIn("xss", tokenize("reflected XSS here"))


class TestVerdictStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = VerdictStore(Path(self.tmp.name) / "memory.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self, fid, title, target, body):
        self.store.add(
            {
                "finding_id": fid,
                "title": title,
                "target": target,
                "body": body,
                "status": "accept",
                "severity": "High",
                "confidence": 0.9,
                "reason": "seeded verdict for recall tests",
                "duplicate_of": "",
            }
        )

    def test_recall_finds_duplicate(self):
        f1 = parse_finding_file(FIXTURES / "01-xss-login.md")
        self._seed(f1["id"], f1["title"], f1["target"], f1["body"])
        f2 = parse_finding_file(FIXTURES / "02-xss-login-duplicate.md")
        matches = self.store.recall(f2)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["finding_id"], "01-xss-login")

    def test_recall_empty_when_unrelated(self):
        f1 = parse_finding_file(FIXTURES / "01-xss-login.md")
        self._seed(f1["id"], f1["title"], f1["target"], f1["body"])
        f5 = parse_finding_file(FIXTURES / "05-no-rate-limit-login.md")
        self.assertEqual(self.store.recall(f5), [])

    def test_store_persists_across_instances(self):
        f1 = parse_finding_file(FIXTURES / "01-xss-login.md")
        self._seed(f1["id"], f1["title"], f1["target"], f1["body"])
        again = VerdictStore(Path(self.tmp.name) / "memory.json")
        self.assertEqual(len(again.verdicts), 1)
        self.assertEqual(again.get("01-xss-login")["severity"], "High")

    def test_recall_ignores_non_accepted(self):
        self.store.add(
            {
                "finding_id": "10-vague-insecure",
                "title": "Site looks insecure",
                "target": "https://example-shop.test/",
                "body": "feels insecure, no evidence",
                "status": "reject",
                "severity": "",
                "confidence": 0.9,
                "reason": "no evidence",
                "duplicate_of": "",
            }
        )
        f = {"title": "Site looks insecure", "target": "https://example-shop.test/", "body": "feels insecure"}
        self.assertEqual(self.store.recall(f), [])


class TestValidateVerdict(unittest.TestCase):
    def test_good_verdict_passes(self):
        self.assertEqual(
            validate_verdict("accept", "High", 0.8, "Reflected input is executed without encoding."),
            [],
        )

    def test_bad_severity_rejected(self):
        errs = validate_verdict("accept", "Severe", 0.8, "Reasonable reason text here.")
        self.assertTrue(any("severity" in e for e in errs))

    def test_bad_confidence_rejected(self):
        errs = validate_verdict("accept", "High", 1.5, "Reasonable reason text here.")
        self.assertTrue(any("confidence" in e for e in errs))

    def test_short_reason_rejected(self):
        self.assertTrue(validate_verdict("accept", "High", 0.8, "bad"))

    def test_duplicate_requires_link(self):
        errs = validate_verdict("duplicate", "", 0.9, "Same root cause as the earlier finding.")
        self.assertTrue(any("duplicate_of" in e for e in errs))

    def test_duplicate_with_link_passes(self):
        self.assertEqual(
            validate_verdict(
                "duplicate", "", 0.9, "Same root cause as the earlier finding.",
                duplicate_of="01-xss-login",
            ),
            [],
        )


class TestParsingAndReport(unittest.TestCase):
    def test_parse_markdown(self):
        f = parse_finding_file(FIXTURES / "01-xss-login.md")
        self.assertEqual(f["id"], "01-xss-login")
        self.assertIn("XSS", f["title"])
        self.assertIn("example-shop.test/login", f["target"])
        self.assertIn("script", f["body"].lower())

    def test_parse_json(self):
        f = parse_finding_file(FIXTURES / "03-sqli-search.json")
        self.assertEqual(f["id"], "03-sqli-search")
        self.assertEqual(f["title"], "SQL injection in product search")

    def test_render_report_has_sections(self):
        f = parse_finding_file(FIXTURES / "01-xss-login.md")
        verdict = {
            "status": "accept",
            "severity": "High",
            "confidence": 0.85,
            "reason": "Reflected input is executed without encoding.",
        }
        md = render_report(f, verdict)
        for section in ("# Reflected XSS", "**Severity:** High", "## Summary", "## Evidence", "## Suggested fix"):
            self.assertIn(section, md)

    def test_fixture_ids_match_expected_table(self):
        ids = sorted(p.stem for p in FIXTURES.iterdir() if p.suffix in (".md", ".json"))
        self.assertEqual(ids, sorted(EXPECTED))


if __name__ == "__main__":
    unittest.main(verbosity=2)
