"""The fake gh must record argv and answer the two read commands the scripts use."""
import json
import os
import subprocess
import tempfile
import unittest

import helpers


class FakeGhTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def run_gh(self, args, env):
        return subprocess.run(["gh"] + args, env=env, capture_output=True, text=True)

    def test_records_argv_as_jsonl(self):
        env, log = helpers.fake_gh_env(self.tmp)
        self.run_gh(["issue", "edit", "5", "--add-label", "bug,needs info"], env)
        self.assertEqual(
            helpers.gh_calls(log),
            [["issue", "edit", "5", "--add-label", "bug,needs info"]],
        )

    def test_label_list_returns_canned_labels(self):
        env, _ = helpers.fake_gh_env(self.tmp, labels=["bug", "docs"])
        p = self.run_gh(["label", "list", "--repo", "o/r", "--json", "name"], env)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout), [{"name": "bug"}, {"name": "docs"}])

    def test_issue_view_returns_author_with_per_issue_override(self):
        env, _ = helpers.fake_gh_env(self.tmp, author="reporter", authors={7: "maintainer"})
        p = self.run_gh(["issue", "view", "7", "--repo", "o/r", "--json", "author"], env)
        self.assertEqual(json.loads(p.stdout), {"author": {"login": "maintainer"}})
        p = self.run_gh(["issue", "view", "8", "--repo", "o/r", "--json", "author"], env)
        self.assertEqual(json.loads(p.stdout), {"author": {"login": "reporter"}})

    def test_fail_on_substring_exits_nonzero(self):
        env, _ = helpers.fake_gh_env(self.tmp, fail_on="issue close")
        p = self.run_gh(["issue", "close", "9", "--repo", "o/r"], env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("fake gh failure", p.stderr)
        ok = self.run_gh(["issue", "comment", "9", "--repo", "o/r"], env)
        self.assertEqual(ok.returncode, 0)

    def test_repo_root_contains_scripts_dir(self):
        self.assertTrue(os.path.isdir(os.path.join(helpers.REPO_ROOT, "tests")))


if __name__ == "__main__":
    unittest.main()
