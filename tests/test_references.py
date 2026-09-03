"""The investigator brief template must stay in sync with the schema and the scripts."""
import json
import os
import re
import unittest

import helpers

REFERENCES = os.path.join(helpers.REPO_ROOT, "references")
with open(os.path.join(REFERENCES, "investigator-brief.md")) as fh:
    BRIEF = fh.read()
with open(os.path.join(REFERENCES, "verdict-schema.json")) as fh:
    SCHEMA = json.load(fh)

EXPECTED_PLACEHOLDERS = {
    "repo", "checkout_path", "branch", "baseline_commit", "prior_triage_path", "output_dir",
}


class InvestigatorBriefTest(unittest.TestCase):
    def test_placeholders_are_exactly_the_documented_set(self):
        found = set(re.findall(r"\{\{(\w+)\}\}", BRIEF))
        self.assertEqual(found, EXPECTED_PLACEHOLDERS)

    def test_every_verdict_in_the_schema_is_defined_in_the_brief(self):
        for name in SCHEMA["properties"]["verdict"]["enum"]:
            self.assertIn(name, BRIEF, "%s is in the schema but not the brief" % name)

    def test_every_verdict_constant_in_the_brief_is_in_the_schema(self):
        enum = set(SCHEMA["properties"]["verdict"]["enum"])
        for name in set(re.findall(r"`([A-Z][A-Z_]{4,})`", BRIEF)):
            self.assertIn(name, enum, "%s is in the brief but not the schema" % name)

    def test_brief_points_at_the_schema_not_a_second_copy_of_it(self):
        self.assertIn("references/verdict-schema.json", BRIEF)

    def test_brief_states_the_wave_one_no_live_sessions_rule(self):
        self.assertIn("NEED_LIVE_REPRO", BRIEF)
        self.assertRegex(BRIEF, r"(?i)wave 1[^\n]*no live")

    def test_brief_covers_wave_two_mechanics(self):
        for phrase in [r"cost lever", r"rep cap", r"fixture", r"save every rep",
                       r"neutral prompt"]:
            self.assertRegex(BRIEF, r"(?i)" + phrase)

    def test_brief_carries_the_skepticism_protocol(self):
        self.assertRegex(BRIEF, r"(?i)unreliable narrator")
        self.assertRegex(BRIEF, r"(?i)hypothesis")

    def test_no_hardcoded_project_identity(self):
        for leak in ["obra/superpowers", "Jesse", "Fable", "session_01"]:
            self.assertNotIn(leak, BRIEF)


class VerdictOrderTest(unittest.TestCase):
    def test_report_order_covers_every_schema_verdict(self):
        br = helpers.load_script("build-report.py")
        self.assertEqual(sorted(br.VERDICT_ORDER),
                         sorted(SCHEMA["properties"]["verdict"]["enum"]))


if __name__ == "__main__":
    unittest.main()
