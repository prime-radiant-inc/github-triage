"""check-label-proposals.py: catch self-contradicting or stale label proposals before
anything is applied, and write an apply-triage-actions.py actions file only when clean."""
import json
import os
import shutil
import tempfile
import unittest

import helpers

LIVE_ISSUES = [
    {"number": 10, "author": {"login": "reporter"}, "labels": [{"name": "bug"}]},
    {"number": 11, "author": {"login": "dana"}, "labels": []},
    {"number": 12, "author": {"login": "helper-sen"}, "labels": [{"name": "plans"}]},
]
LIVE_PRS = [
    {"number": 20, "author": {"login": "drive-by"}, "labels": [], "baseRefName": "main"},
    {"number": 21, "author": {"login": "drive-by"}, "labels": [], "baseRefName": "dev"},
    {"number": 22, "author": {"login": "dana"}, "labels": [], "baseRefName": "plan-set"},
]


def proposal(number, kind, **fields):
    record = {
        "number": number, "kind": kind, "title": "t%d" % number,
        "add": [], "remove": [],
        "no_human_review": False, "human_review_evidence": "",
        "template_ignored": False, "template_evidence": "complete",
        "confidence": "high", "notes": "",
    }
    record.update(fields)
    return record


class CheckLabelProposalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proposals = os.path.join(self.tmp, "proposals")
        os.mkdir(self.proposals)
        self.issues = self.write("issues.json", LIVE_ISSUES)
        self.prs = self.write("prs.json", LIVE_PRS)
        self.actions = os.path.join(self.tmp, "actions.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path

    def batch(self, *records, name="batch-01.json"):
        with open(os.path.join(self.proposals, name), "w") as fh:
            json.dump(list(records), fh)

    def run_it(self, *extra):
        args = ["--proposals", self.proposals, "--issues", self.issues, "--prs", self.prs,
                "--actions-out", self.actions] + list(extra)
        return helpers.run_script("check-label-proposals.py", args, dict(os.environ),
                                  self.tmp)

    def actions_written(self):
        with open(self.actions) as fh:
            return json.load(fh)

    # --- clean runs -----------------------------------------------------------------

    def test_clean_proposals_write_keep_actions_with_only_real_changes(self):
        self.batch(proposal(10, "issue", add=["bug", "windows"]),
                   proposal(21, "pr", add=[]))
        proc = self.run_it()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.actions_written(), {"issues": {
            "10": {"action": "keep", "labels_add": ["windows"], "labels_remove": []}}})
        self.assertIn("--approved 10", proc.stdout)

    def test_remove_keeps_only_labels_the_item_has(self):
        self.batch(proposal(10, "issue", remove=["bug", "ghost"]))
        proc = self.run_it()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.actions_written()["issues"]["10"]["labels_remove"], ["bug"])

    def test_overrides_replace_subagent_fields(self):
        self.batch(proposal(10, "issue", add=["windows"]))
        overrides = self.write("overrides.json", {"10": {"add": ["linux"]}})
        proc = self.run_it("--overrides", overrides)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.actions_written()["issues"]["10"]["labels_add"], ["linux"])

    # --- contradictions block the actions file ---------------------------------------

    def assert_problem(self, proc, text):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(text, proc.stdout)
        self.assertFalse(os.path.exists(self.actions), "actions file written despite problems")

    def test_template_flag_without_label(self):
        self.batch(proposal(10, "issue", template_ignored=True))
        self.assert_problem(self.run_it(), "#10: template_ignored is true but "
                                           "issue-template-rules-ignored is not applied")

    def test_template_label_without_flag(self):
        self.batch(proposal(20, "pr", add=["pr-template-rules-ignored",
                                           "needs-rebase-to-dev-branch"]))
        self.assert_problem(self.run_it(), "#20: pr-template-rules-ignored is applied but "
                                           "template_ignored is false")

    def test_template_label_of_the_wrong_kind(self):
        self.batch(proposal(10, "issue", template_ignored=True,
                            add=["pr-template-rules-ignored",
                                 "issue-template-rules-ignored"]))
        self.assert_problem(self.run_it(), "#10: pr-template-rules-ignored on an issue")

    def test_review_flag_without_label(self):
        self.batch(proposal(21, "pr", no_human_review=True))
        self.assert_problem(self.run_it(), "#21: no_human_review is true but "
                                           "no-obvious-human-review is not applied")

    def test_review_label_without_flag(self):
        self.batch(proposal(21, "pr", add=["no-obvious-human-review"]))
        self.assert_problem(self.run_it(), "#21: no-obvious-human-review is applied but "
                                           "no_human_review is false")

    def test_item_no_longer_open(self):
        self.batch(proposal(99, "issue"))
        self.assert_problem(self.run_it(), "#99: not an open issue")

    def test_retired_label_left_behind(self):
        self.batch(proposal(12, "issue"))
        self.assert_problem(self.run_it("--retired", "plans,tdd"),
                            "#12: retired label still applied: plans")

    def test_rebase_label_must_match_live_base(self):
        self.batch(proposal(20, "pr"), proposal(21, "pr", add=["needs-rebase-to-dev-branch"]))
        proc = self.run_it("--wrong-base", "main",
                           "--rebase-label", "needs-rebase-to-dev-branch")
        self.assert_problem(proc, "#20: base is main but "
                                  "needs-rebase-to-dev-branch is not applied")
        self.assertIn("#21: base is dev, not main, but needs-rebase-to-dev-branch is applied",
                      proc.stdout)

    def test_stacked_pr_on_a_feature_branch_needs_no_rebase_label(self):
        self.batch(proposal(22, "pr"))
        self.assertEqual(self.run_it("--wrong-base", "main").returncode, 0)

    def test_rebase_check_is_off_without_wrong_base(self):
        self.batch(proposal(20, "pr"))
        self.assertEqual(self.run_it().returncode, 0)

    def test_every_problem_is_listed_not_just_the_first(self):
        self.batch(proposal(10, "issue", template_ignored=True),
                   proposal(21, "pr", no_human_review=True), name="batch-01.json")
        proc = self.run_it()
        self.assertIn("#10:", proc.stdout)
        self.assertIn("#21:", proc.stdout)

    # --- exempt authors ---------------------------------------------------------------

    def test_exempt_author_loses_review_and_template_labels_only(self):
        self.batch(proposal(11, "issue", template_ignored=True, no_human_review=True,
                            add=["issue-template-rules-ignored", "no-obvious-human-review",
                                 "windows"]))
        proc = self.run_it("--exempt", "dana")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.actions_written()["issues"]["11"]["labels_add"], ["windows"])
        self.assertIn("#11: exempt author dana", proc.stdout)

    def test_exempt_accepts_glob_patterns(self):
        self.batch(proposal(12, "issue", template_ignored=True, remove=["plans"],
                            add=["issue-template-rules-ignored", "skill:writing-plans"]))
        proc = self.run_it("--exempt", "dana,*-sen")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.actions_written()["issues"]["12"]["labels_add"],
                         ["skill:writing-plans"])

    # --- malformed input --------------------------------------------------------------

    def test_malformed_proposal_exits_2_and_names_the_file(self):
        bad = proposal(10, "issue")
        del bad["add"]
        self.batch(bad, name="batch-07.json")
        proc = self.run_it()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("batch-07.json", proc.stderr)
        self.assertIn("add", proc.stderr)
        self.assertFalse(os.path.exists(self.actions))

    def test_unparseable_batch_exits_2(self):
        with open(os.path.join(self.proposals, "batch-03.json"), "w") as fh:
            fh.write("[{not json")
        proc = self.run_it()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("batch-03.json", proc.stderr)


if __name__ == "__main__":
    unittest.main()
