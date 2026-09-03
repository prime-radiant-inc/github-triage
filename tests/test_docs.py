"""SKILL.md Phase 6 and the README must point at the tooling that ships with the plugin."""
import os
import unittest

import helpers

with open(os.path.join(helpers.REPO_ROOT, "skills", "github-triage", "SKILL.md")) as fh:
    SKILL = fh.read()
with open(os.path.join(helpers.REPO_ROOT, "README.md")) as fh:
    README = fh.read()

ARTIFACTS = [
    "scripts/build-report.py",
    "scripts/apply-triage-actions.py",
    "references/verdict-schema.json",
    "references/investigator-brief.md",
]


def phase_six():
    return SKILL.split("## Phase 6")[1].split("## Phase 7")[0]


class SkillPointerTest(unittest.TestCase):
    def test_phase_six_names_every_artifact(self):
        section = phase_six()
        for artifact in ARTIFACTS:
            self.assertIn(artifact, section, "%s missing from Phase 6" % artifact)

    def test_phase_six_states_the_two_wave_split(self):
        section = phase_six()
        self.assertIn("NEED_LIVE_REPRO", section)
        self.assertRegex(section, r"(?i)wave 1")
        self.assertRegex(section, r"(?i)wave 2")

    def test_phase_six_states_the_model_budget_rule(self):
        self.assertRegex(phase_six(), r"(?i)cheapest model")

    def test_phase_seven_still_present_and_after_phase_six(self):
        self.assertIn("## Phase 7: PR Review and Merge", SKILL)
        self.assertLess(SKILL.index("## Phase 6"), SKILL.index("## Phase 7"))


class ReadmeTest(unittest.TestCase):
    def test_readme_documents_every_artifact(self):
        for artifact in ARTIFACTS:
            self.assertIn(artifact, README, "%s missing from the README" % artifact)

    def test_readme_documents_the_test_runner(self):
        self.assertIn("tests/run-tests.sh", README)


if __name__ == "__main__":
    unittest.main()
