"""build-report.py: schema enforcement, report rendering, and the --missing check."""
import json
import os
import shutil
import tempfile
import unittest

import helpers

VALID = {
    "n": 10,
    "verdict": "REPRODUCED",
    "confidence": "high",
    "summary": "Still happens on main.",
    "evidence": [{"claim": "c", "test": "t", "result": "r"}],
    "related": {"duplicates_of": None, "open_prs": [], "related_issues": []},
    "recommended_action": "keep",
    "labels_add": ["bug"],
    "labels_remove": [],
    "draft_reply": "",
    "live_repro_design": None,
}


def verdict(n, **over):
    v = json.loads(json.dumps(VALID))
    v["n"] = n
    v.update(over)
    return v


class BuildReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.verdicts = os.path.join(self.tmp, "verdicts")
        os.makedirs(self.verdicts)
        self.env = dict(os.environ)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, v):
        with open(os.path.join(self.verdicts, "%d.json" % v["n"]), "w") as fh:
            json.dump(v, fh)

    def write_issues(self, numbers):
        path = os.path.join(self.tmp, "issues.json")
        with open(path, "w") as fh:
            json.dump([{"number": n, "title": "Issue %d title" % n} for n in numbers], fh)
        return path

    def run_it(self, *args):
        return helpers.run_script("build-report.py", args, self.env, self.tmp)

    def read_md(self):
        with open(os.path.join(self.tmp, "report.md")) as fh:
            return fh.read()

    def test_valid_verdicts_produce_report_and_json(self):
        self.write(verdict(10))
        self.write(verdict(11, verdict="SLOP", recommended_action="close",
                           draft_reply="Closing.", summary="Nothing to do with this repo."))
        p = self.run_it("--verdicts", self.verdicts)
        self.assertEqual(p.returncode, 0, p.stderr)
        md = self.read_md()
        self.assertIn("| Verdict | Count |", md)
        self.assertIn("| REPRODUCED | 1 |", md)
        self.assertIn("| SLOP | 1 |", md)
        self.assertIn("## REPRODUCED (1)", md)
        self.assertIn("Still happens on main.", md)
        with open(os.path.join(self.tmp, "verdicts.json")) as fh:
            out = json.load(fh)
        self.assertEqual([v["n"] for v in out], [10, 11])

    def test_titles_come_from_the_issues_file(self):
        self.write(verdict(10))
        issues = self.write_issues([10, 11])
        p = self.run_it("--verdicts", self.verdicts, "--issues", issues)
        self.assertEqual(p.returncode, 0, p.stderr)
        md = self.read_md()
        self.assertIn("Issue 10 title", md)
        self.assertIn("No verdict yet: [11]", md)
        self.assertIn("1/2", md)

    def test_custom_title_is_used(self):
        self.write(verdict(10))
        self.run_it("--verdicts", self.verdicts, "--title", "Acme triage, wave 1")
        self.assertIn("# Acme triage, wave 1", self.read_md())

    def test_schema_violation_fails_and_names_file_and_path(self):
        self.write(verdict(10))
        bad = verdict(11)
        bad["verdict"] = "PROBABLY"
        self.write(bad)
        p = self.run_it("--verdicts", self.verdicts)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("11.json", p.stderr)
        self.assertIn("PROBABLY", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "report.md")))

    def test_unparseable_json_fails_with_the_filename(self):
        self.write(verdict(10))
        with open(os.path.join(self.verdicts, "12.json"), "w") as fh:
            fh.write("{not json")
        p = self.run_it("--verdicts", self.verdicts)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("12.json", p.stderr)

    def test_missing_lists_open_issues_without_a_verdict(self):
        self.write(verdict(10))
        issues = self.write_issues([10, 11, 12])
        p = self.run_it("--verdicts", self.verdicts, "--issues", issues, "--missing")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("1/3", p.stdout)
        self.assertIn("11", p.stdout)
        self.assertIn("12", p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "report.md")))

    def test_missing_requires_issues(self):
        p = self.run_it("--verdicts", self.verdicts, "--missing")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--issues", p.stderr)

    def test_label_changes_section(self):
        self.write(verdict(10, labels_add=["bug", "hooks"], labels_remove=["needs-triage"]))
        self.run_it("--verdicts", self.verdicts)
        md = self.read_md()
        self.assertIn("## Label changes proposed", md)
        self.assertIn("#10: +['bug', 'hooks'] -['needs-triage']", md)

    def test_live_repro_queue_lists_designs_and_results(self):
        design = {"fixture": "f", "prompt": "p", "model": "sonnet",
                  "decisive_observation": "does it say feat:", "reps": 3}
        self.write(verdict(10, verdict="NEED_LIVE_REPRO", live_repro_design=design))
        self.write(verdict(11, verdict="REPRODUCED", live_repro_design=design,
                           live_repro={"reps": 3, "reproduced": 1, "void": 0,
                                       "workers": ["t11-r1"], "notes": ""}))
        self.run_it("--verdicts", self.verdicts)
        md = self.read_md()
        self.assertIn("## Live-repro queue (wave 2)", md)
        self.assertIn("#10 (sonnet, reps 3): pending", md)
        self.assertIn("#11", md)
        self.assertIn("1/3 reproduced", md)

    def test_recommended_actions_counts(self):
        self.write(verdict(10, recommended_action="keep"))
        self.write(verdict(11, recommended_action="close", draft_reply="bye"))
        self.write(verdict(12, recommended_action="close", draft_reply="bye"))
        self.run_it("--verdicts", self.verdicts)
        md = self.read_md()
        self.assertIn("## Recommended actions", md)
        self.assertIn("| close | 2 |", md)
        self.assertIn("| keep | 1 |", md)

    def test_empty_verdicts_dir_is_not_an_error(self):
        p = self.run_it("--verdicts", self.verdicts)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("# Issue triage report", self.read_md())


if __name__ == "__main__":
    unittest.main()
