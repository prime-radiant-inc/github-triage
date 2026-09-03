"""The verdict schema and the JSON Schema subset validator that enforces it."""
import copy
import json
import os
import unittest

import helpers

br = helpers.load_script("build-report.py")

with open(os.path.join(helpers.REPO_ROOT, "references", "verdict-schema.json")) as fh:
    SCHEMA = json.load(fh)


def minimal_verdict():
    return {
        "n": 42,
        "verdict": "REPRODUCED",
        "confidence": "high",
        "summary": "Reproduced on current dev.",
        "evidence": [{"claim": "c", "test": "t", "result": "r"}],
        "related": {"duplicates_of": None, "open_prs": [], "related_issues": []},
        "recommended_action": "keep",
        "labels_add": [],
        "labels_remove": [],
        "draft_reply": "",
        "live_repro_design": None,
    }


class ValidatorTest(unittest.TestCase):
    def test_type_mismatch_names_the_path(self):
        errors = br.validate({"a": {"b": 1}}, {
            "type": "object",
            "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}},
        })
        self.assertEqual(len(errors), 1)
        self.assertIn("a.b", errors[0])
        self.assertIn("string", errors[0])

    def test_array_item_errors_carry_the_index(self):
        errors = br.validate({"xs": ["ok", 3]}, {
            "type": "object",
            "properties": {"xs": {"type": "array", "items": {"type": "string"}}},
        })
        self.assertEqual(len(errors), 1)
        self.assertIn("xs[1]", errors[0])

    def test_missing_required_property_is_reported(self):
        errors = br.validate({}, {"type": "object", "required": ["n"]})
        self.assertEqual(len(errors), 1)
        self.assertIn("n", errors[0])
        self.assertIn("required", errors[0])

    def test_enum_rejects_unlisted_value(self):
        errors = br.validate("MAYBE", {"enum": ["YES", "NO"]})
        self.assertEqual(len(errors), 1)
        self.assertIn("MAYBE", errors[0])

    def test_nullable_via_type_list(self):
        schema = {"type": ["string", "null"]}
        self.assertEqual(br.validate(None, schema), [])
        self.assertEqual(br.validate("x", schema), [])
        self.assertEqual(len(br.validate(3, schema)), 1)

    def test_bool_is_not_an_integer(self):
        self.assertEqual(len(br.validate(True, {"type": "integer"})), 1)

    def test_additional_properties_false_rejects_unknown_key(self):
        errors = br.validate({"a": 1, "zz": 2}, {
            "type": "object", "properties": {"a": {"type": "integer"}},
            "additionalProperties": False,
        })
        self.assertEqual(len(errors), 1)
        self.assertIn("zz", errors[0])

    def test_ref_is_resolved_against_defs(self):
        schema = {
            "type": "object",
            "properties": {"e": {"$ref": "#/$defs/thing"}},
            "$defs": {"thing": {"type": "object", "required": ["k"]}},
        }
        errors = br.validate({"e": {}}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("e", errors[0])

    def test_min_items_and_min_length(self):
        self.assertEqual(len(br.validate([], {"type": "array", "minItems": 1})), 1)
        self.assertEqual(len(br.validate("", {"type": "string", "minLength": 1})), 1)


class VerdictSchemaTest(unittest.TestCase):
    def test_minimal_verdict_validates(self):
        self.assertEqual(br.validate(minimal_verdict(), SCHEMA), [])

    def test_unknown_verdict_value_rejected(self):
        v = minimal_verdict()
        v["verdict"] = "PROBABLY_FINE"
        self.assertTrue(br.validate(v, SCHEMA))

    def test_unknown_recommended_action_rejected(self):
        v = minimal_verdict()
        v["recommended_action"] = "yolo"
        self.assertTrue(br.validate(v, SCHEMA))

    def test_needs_maintainer_is_a_valid_action(self):
        v = minimal_verdict()
        v["recommended_action"] = "needs-maintainer"
        self.assertEqual(br.validate(v, SCHEMA), [])

    def test_typo_in_key_is_rejected(self):
        v = minimal_verdict()
        v["labels_ad"] = v.pop("labels_add")
        self.assertTrue(br.validate(v, SCHEMA))

    def test_missing_required_field_rejected(self):
        v = minimal_verdict()
        del v["summary"]
        self.assertTrue(br.validate(v, SCHEMA))

    def test_live_repro_design_shape_is_enforced(self):
        v = minimal_verdict()
        v["verdict"] = "NEED_LIVE_REPRO"
        v["live_repro_design"] = {
            "fixture": "empty git repo",
            "prompt": "Write a plan for docs/spec.md",
            "model": "sonnet",
            "decisive_observation": "does the commit step say feat:",
            "reps": 3,
        }
        self.assertEqual(br.validate(v, SCHEMA), [])
        bad = copy.deepcopy(v)
        del bad["live_repro_design"]["decisive_observation"]
        self.assertTrue(br.validate(bad, SCHEMA))

    def test_live_repro_results_shape_is_enforced(self):
        v = minimal_verdict()
        v["live_repro"] = {"reps": 3, "reproduced": 1, "void": 0,
                           "workers": ["t42-r1"], "notes": "1/3"}
        self.assertEqual(br.validate(v, SCHEMA), [])
        v["live_repro"] = {"reps": "three"}
        self.assertTrue(br.validate(v, SCHEMA))

    def test_changed_since_baseline_is_optional_and_nullable(self):
        v = minimal_verdict()
        self.assertEqual(br.validate(v, SCHEMA), [])
        v["changed_since_baseline"] = None
        self.assertEqual(br.validate(v, SCHEMA), [])
        v["changed_since_baseline"] = "none"
        self.assertEqual(br.validate(v, SCHEMA), [])


if __name__ == "__main__":
    unittest.main()
