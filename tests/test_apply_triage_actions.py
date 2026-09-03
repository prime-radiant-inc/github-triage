"""apply-triage-actions.py: refuse-before-mutating, label safety, and comment bodies."""
import json
import os
import shutil
import tempfile
import unittest

import helpers

IDENTITY = {
    "model": "Claude Opus 5",
    "harness": "Claude Code 2.1.259",
    "session_url": "https://claude.ai/code/session_abc",
    "maintainer": "obra",
    "maintainer_name": "Jesse",
}


class ApplyActionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.identity = os.path.join(self.tmp, "identity.json")
        with open(self.identity, "w") as fh:
            json.dump(IDENTITY, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def actions_file(self, issues, new_labels=None):
        path = os.path.join(self.tmp, "actions.json")
        with open(path, "w") as fh:
            json.dump({"new_labels": new_labels or {}, "issues": issues}, fh)
        return path

    def run_it(self, args, labels=(), author="reporter", authors=None, fail_on=None):
        env, log = helpers.fake_gh_env(self.tmp, labels=labels, author=author,
                                       authors=authors, fail_on=fail_on)
        proc = helpers.run_script("apply-triage-actions.py", args, env, self.tmp)
        return proc, helpers.gh_calls(log)

    def base(self, actions):
        return ["--repo", "o/r", "--actions", actions, "--identity", self.identity]

    @staticmethod
    def mutating(calls):
        return [c for c in calls if c[:2] in (["issue", "edit"], ["issue", "close"],
                                              ["issue", "comment"], ["label", "create"])]

    @staticmethod
    def body_of(call):
        for flag in ("--body", "--comment"):
            if flag in call:
                return call[call.index(flag) + 1]
        raise AssertionError("no body in %r" % (call,))

    # --- refusals, before anything is touched -------------------------------------

    def test_refuses_label_not_in_repo(self):
        actions = self.actions_file({"1": {"labels_add": ["ghost"], "action": "keep"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], labels=["bug"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ghost", proc.stderr)
        self.assertEqual(self.mutating(calls), [])

    def test_refuses_label_removal_not_in_repo(self):
        actions = self.actions_file({"1": {"labels_remove": ["ghost"], "action": "keep"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], labels=["bug"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ghost", proc.stderr)
        self.assertEqual(self.mutating(calls), [])

    def test_refuses_approved_issue_missing_from_actions_file(self):
        actions = self.actions_file({"1": {"action": "keep"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1,2"], labels=["bug"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("2", proc.stderr)
        self.assertEqual(self.mutating(calls), [])

    def test_refuses_unknown_action(self):
        actions = self.actions_file({"1": {"action": "nuke"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("nuke", proc.stderr)
        self.assertEqual(self.mutating(calls), [])

    def test_refuses_close_with_empty_reply(self):
        actions = self.actions_file({"1": {"action": "close", "reply": "  "}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("reply", proc.stderr)
        self.assertEqual(self.mutating(calls), [])

    def test_refuses_when_identity_is_incomplete(self):
        actions = self.actions_file({"1": {"action": "keep"}})
        proc, _ = self.run_it(["--repo", "o/r", "--actions", actions,
                               "--approved", "1", "--model", "Opus"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("harness", proc.stderr)

    def test_refuses_an_empty_approved_list(self):
        actions = self.actions_file({"1": {"action": "keep"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", ""])
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.mutating(calls), [])

    # --- selection ----------------------------------------------------------------

    def test_only_approved_issues_are_touched(self):
        actions = self.actions_file({
            "1": {"labels_add": ["bug"], "action": "keep"},
            "2": {"labels_add": ["bug"], "action": "keep"},
        })
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        edits = [c for c in calls if c[:2] == ["issue", "edit"]]
        self.assertEqual([c[2] for c in edits], ["1"])

    # --- labels -------------------------------------------------------------------

    def test_creates_only_declared_new_labels_that_do_not_exist(self):
        actions = self.actions_file(
            {"1": {"labels_add": ["bug", "hermes"], "action": "keep"}},
            new_labels={"hermes": {"color": "5319e7", "description": "Hermes"},
                        "bug": {"color": "d73a4a", "description": "Bug"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        creates = [c for c in calls if c[:2] == ["label", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0][2], "hermes")
        self.assertIn("5319e7", creates[0])

    def test_declared_new_label_no_issue_wants_is_not_created(self):
        actions = self.actions_file(
            {"1": {"labels_add": ["bug"], "action": "keep"}},
            new_labels={"unused": {"color": "ffffff", "description": "Unused"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([c for c in calls if c[:2] == ["label", "create"]], [])

    def test_label_edit_uses_add_and_remove_flags(self):
        actions = self.actions_file({"1": {"labels_add": ["bug", "docs"],
                                           "labels_remove": ["stale"], "action": "keep"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"],
                                  labels=["bug", "docs", "stale"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        edit = [c for c in calls if c[:2] == ["issue", "edit"]][0]
        self.assertEqual(edit[edit.index("--add-label") + 1], "bug,docs")
        self.assertEqual(edit[edit.index("--remove-label") + 1], "stale")

    def test_only_labels_skips_comments_and_closes(self):
        actions = self.actions_file({"1": {"labels_add": ["bug"], "action": "close",
                                           "reply": "Closing."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1", "--only-labels"],
                                  labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue([c for c in calls if c[:2] == ["issue", "edit"]])
        self.assertEqual([c for c in calls if c[:2] == ["issue", "close"]], [])

    # --- comments and closes ------------------------------------------------------

    def test_close_posts_comment_and_closes_as_not_planned(self):
        actions = self.actions_file({"1": {"action": "close", "reply": "Not our bug."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        close = [c for c in calls if c[:2] == ["issue", "close"]][0]
        self.assertEqual(close[close.index("--reason") + 1], "not planned")
        self.assertIn("Not our bug.", self.body_of(close))

    def test_comment_leaves_the_issue_open(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "Still open."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue([c for c in calls if c[:2] == ["issue", "comment"]])
        self.assertEqual([c for c in calls if c[:2] == ["issue", "close"]], [])

    def test_keep_posts_nothing(self):
        actions = self.actions_file({"1": {"labels_add": ["bug"], "action": "keep",
                                           "reply": "unused"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([c for c in calls if c[:2] in (["issue", "close"],
                                                        ["issue", "comment"])], [])

    def test_reporter_preamble_addresses_the_author(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "Body."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], author="octocat")
        body = self.body_of([c for c in calls if c[:2] == ["issue", "comment"]][0])
        self.assertIn("Hi @octocat", body)
        self.assertIn("Claude Opus 5", body)
        self.assertIn("Claude Code 2.1.259", body)
        self.assertIn("Jesse", body)
        self.assertIn("@obra", body)
        self.assertIn("Body.", body)
        self.assertIn("https://claude.ai/code/session_abc", body)

    def test_maintainer_authored_issue_gets_the_self_preamble(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "Body."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"], author="obra")
        body = self.body_of([c for c in calls if c[:2] == ["issue", "comment"]][0])
        self.assertNotIn("Hi @obra", body)
        self.assertIn("Triage note", body)
        self.assertIn("Body.", body)

    def test_preamble_choice_is_per_issue(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "One."},
                                     "2": {"action": "comment", "reply": "Two."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1,2"],
                                  author="octocat", authors={2: "obra"})
        comments = [c for c in calls if c[:2] == ["issue", "comment"]]
        self.assertIn("Hi @octocat", self.body_of(comments[0]))
        self.assertIn("Triage note", self.body_of(comments[1]))

    def test_close_and_reply_kinds_differ_in_the_preamble(self):
        actions = self.actions_file({"1": {"action": "close", "reply": "Bye."},
                                     "2": {"action": "comment", "reply": "Hi."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1,2"])
        close = [c for c in calls if c[:2] == ["issue", "close"]][0]
        comment = [c for c in calls if c[:2] == ["issue", "comment"]][0]
        self.assertIn("approved this closure", self.body_of(close))
        self.assertIn("approved this reply", self.body_of(comment))

    def test_footer_invites_pushback(self):
        actions = self.actions_file({"1": {"action": "close", "reply": "Bye."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"])
        body = self.body_of([c for c in calls if c[:2] == ["issue", "close"]][0])
        self.assertIn("reply here", body)
        self.assertIn("can be revisited", body)

    def test_footer_omits_the_session_when_none_is_given(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "Body."}})
        proc, calls = self.run_it(["--repo", "o/r", "--actions", actions, "--approved", "1",
                                   "--model", "Opus 5", "--harness", "Claude Code 2.1.259",
                                   "--maintainer", "obra"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.body_of([c for c in calls if c[:2] == ["issue", "comment"]][0])
        self.assertNotIn("session", body)
        self.assertIn("Opus 5", body)

    def test_maintainer_name_defaults_to_the_login(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "Body."}})
        proc, calls = self.run_it(["--repo", "o/r", "--actions", actions, "--approved", "1",
                                   "--model", "Opus 5", "--harness", "CC 2.1",
                                   "--maintainer", "octomaint"])
        body = self.body_of([c for c in calls if c[:2] == ["issue", "comment"]][0])
        self.assertIn("@octomaint", body)
        self.assertNotIn("@octomaint (@octomaint)", body)

    def test_flags_override_the_identity_file(self):
        actions = self.actions_file({"1": {"action": "comment", "reply": "Body."}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1",
                                                        "--model", "Claude Haiku 4.5"])
        body = self.body_of([c for c in calls if c[:2] == ["issue", "comment"]][0])
        self.assertIn("Claude Haiku 4.5", body)
        self.assertNotIn("Claude Opus 5", body)

    # --- dry run, logging, failure ------------------------------------------------

    def test_dry_run_mutates_nothing_but_reports_what_it_would_do(self):
        actions = self.actions_file(
            {"1": {"labels_add": ["hermes"], "action": "close", "reply": "Closing."}},
            new_labels={"hermes": {"color": "5319e7", "description": "Hermes"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1", "--dry-run"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.mutating(calls), [])
        self.assertIn("#1", proc.stdout)
        self.assertIn("DRY RUN", proc.stdout)

    def test_gh_failure_stops_immediately_with_nonzero_exit(self):
        actions = self.actions_file({
            "1": {"labels_add": ["bug"], "action": "keep"},
            "2": {"labels_add": ["bug"], "action": "keep"},
        })
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1,2"],
                                  labels=["bug"], fail_on="issue edit 1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("gh failed", proc.stderr)
        edits = [c for c in calls if c[:2] == ["issue", "edit"]]
        self.assertEqual([c[2] for c in edits], ["1"])

    def test_label_list_failure_stops_before_any_mutation(self):
        actions = self.actions_file({"1": {"labels_add": ["bug"], "action": "keep"}})
        proc, calls = self.run_it(self.base(actions) + ["--approved", "1"],
                                  labels=["bug"], fail_on="label list")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.mutating(calls), [])

    def test_log_file_records_every_gh_command(self):
        actions = self.actions_file({"1": {"labels_add": ["bug"], "action": "keep"}})
        log = os.path.join(self.tmp, "run.log")
        proc, _ = self.run_it(self.base(actions) + ["--approved", "1", "--log", log],
                              labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(log) as fh:
            text = fh.read()
        self.assertIn("gh issue edit 1", text)
        self.assertIn("gh label list", text)

    def test_one_line_per_action_on_stdout(self):
        actions = self.actions_file({
            "1": {"labels_add": ["bug"], "action": "keep"},
            "2": {"action": "close", "reply": "Closing."},
        })
        proc, _ = self.run_it(self.base(actions) + ["--approved", "1,2"], labels=["bug"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("#1: labels +bug", proc.stdout)
        self.assertIn("#2: CLOSE", proc.stdout)


if __name__ == "__main__":
    unittest.main()
