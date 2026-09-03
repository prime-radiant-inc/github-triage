#!/usr/bin/env python3
"""Merge per-issue triage verdict files into one report for the maintainer.

When to use: after investigator agents have written verdicts/<n>.json following
references/investigator-brief.md. Re-run any time; it is idempotent. Why: a hundred JSON
files are unreadable as a set, and one file with a typo'd key silently disappears from
every count. This validates each file against references/verdict-schema.json, then emits
the counts, the per-verdict issue lists, the actions that need the maintainer, the
proposed label changes and the wave-2 live-repro queue -- plus a machine-readable
verdicts.json.

Usage:
  build-report.py --verdicts DIR [--issues issues.json] [--md report.md]
                  [--json verdicts.json] [--title TEXT]
  build-report.py --verdicts DIR --issues issues.json --missing

  --issues takes the JSON from:
    gh issue list --repo OWNER/REPO --state open --json number,title --limit 500

Exits non-zero, having written nothing, if any verdict file is unreadable or fails the
schema. --missing is a progress check and tolerates files that are still being written.
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(os.path.dirname(HERE), "references", "verdict-schema.json")

# --- JSON Schema subset validator --------------------------------------------------
# Deliberately small: the plugin ships no dependencies, so it cannot import jsonschema.
# Supported keywords: type, enum, const, required, properties, additionalProperties
# (boolean), items, minItems, minLength, and $ref into #/$defs/<name>. Anything else in
# the schema is ignored, so keep references/verdict-schema.json inside this subset.

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _matches_type(value, name):
    expected = _TYPES.get(name)
    if expected is None:
        return True
    if name in ("integer", "number") and isinstance(value, bool):
        return False  # bools are ints in Python; JSON Schema says they are not numbers
    return isinstance(value, expected)


def validate(instance, schema, root=None, path=""):
    """Return human-readable error strings for instance against schema; [] means valid."""
    root = schema if root is None else root
    errors = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            return ["%s: unsupported $ref %r" % (path or "<root>", ref)]
        target = root.get("$defs", {}).get(ref[len("#/$defs/"):])
        if target is None:
            return ["%s: unresolvable $ref %r" % (path or "<root>", ref)]
        return validate(instance, target, root, path)

    where = path or "<root>"

    if "type" in schema:
        names = schema["type"]
        names = [names] if isinstance(names, str) else names
        if not any(_matches_type(instance, n) for n in names):
            return ["%s: expected %s, got %s"
                    % (where, " or ".join(names), type(instance).__name__)]

    if "enum" in schema and instance not in schema["enum"]:
        return ["%s: %r is not one of %s" % (where, instance, schema["enum"])]

    if "const" in schema and instance != schema["const"]:
        return ["%s: %r is not %r" % (where, instance, schema["const"])]

    minimum = schema.get("minLength", 0)
    if isinstance(instance, str) and len(instance) < minimum:
        errors.append("%s: needs at least %d character(s), got %d"
                      % (where, minimum, len(instance)))

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append("%s: needs at least %d item(s), got %d"
                          % (where, schema["minItems"], len(instance)))
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(instance):
                errors += validate(item, item_schema, root, "%s[%d]" % (path, i))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                errors.append("%s: required property %r is missing" % (where, name))
        if schema.get("additionalProperties") is False:
            for name in sorted(instance):
                if name not in properties:
                    errors.append("%s: unknown property %r" % (where, name))
        for name, value in instance.items():
            if name in properties:
                child = (path + "." + name) if path else name
                errors += validate(value, properties[name], root, child)

    return errors


# --- verdict loading and reporting -------------------------------------------------

VERDICT_ORDER = [
    "REPRODUCED", "RESOLVED_ON_MAIN", "RESOLVED_BY_OPEN_PR", "NOT_REPRODUCIBLE",
    "DUPLICATE", "FEATURE_UNMET", "FEATURE_MET", "OPINION_NOT_BUG", "WRONG_VENUE",
    "SLOP", "NEEDS_MAINTAINER_DECISION", "NEED_LIVE_REPRO", "NEED_REPRO_ENV",
    "NEED_MORE_INFO",
]


def load_verdicts(directory, schema):
    """Read verdicts/*.json. Returns (verdicts keyed by issue number, error strings)."""
    verdicts, errors = {}, []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        name = os.path.basename(path)
        try:
            with open(path) as fh:
                verdict = json.load(fh)
        except ValueError as exc:
            errors.append("%s: not valid JSON: %s" % (name, exc))
            continue
        problems = validate(verdict, schema)
        if problems:
            errors += ["%s: %s" % (name, p) for p in problems]
            continue
        if verdict["n"] in verdicts:
            errors.append("%s: a second verdict for issue #%d" % (name, verdict["n"]))
            continue
        verdicts[verdict["n"]] = verdict
    return verdicts, errors


def render(verdicts, issues, title):
    """Return the report markdown for a validated set of verdicts."""
    counts = Counter(v["verdict"] for v in verdicts.values())
    by_verdict = defaultdict(list)
    for _, verdict in sorted(verdicts.items()):
        by_verdict[verdict["verdict"]].append(verdict)

    scope = "%d/%d" % (len(verdicts), len(issues)) if issues else str(len(verdicts))
    out = ["# %s — %s issues\n" % (title, scope)]

    out.append("| Verdict | Count |")
    out.append("|---|---|")
    for name in VERDICT_ORDER:
        if counts.get(name):
            out.append("| %s | %d |" % (name, counts[name]))

    if issues:
        missing = sorted(set(issues) - set(verdicts))
        if missing:
            out.append("\nNo verdict yet: %s" % missing)

    for name in VERDICT_ORDER:
        group = by_verdict.get(name)
        if not group:
            continue
        out.append("\n## %s (%d)\n" % (name, len(group)))
        out.append("| # | Title | Conf | Action | Summary |")
        out.append("|---|---|---|---|---|")
        for verdict in group:
            heading = issues.get(verdict["n"], {}).get("title", "?")[:70]
            out.append("| #%d | %s | %s | %s | %s |" % (
                verdict["n"], heading.replace("|", "\\|"), verdict["confidence"],
                verdict["recommended_action"],
                verdict["summary"][:220].replace("|", "\\|")))

    actions = Counter(v["recommended_action"] for v in verdicts.values())
    out.append("\n## Recommended actions\n")
    out.append("| Action | Count |")
    out.append("|---|---|")
    for name, count in sorted(actions.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append("| %s | %d |" % (name, count))

    labelled = [(v["n"], v["labels_add"], v["labels_remove"]) for v in verdicts.values()
                if v["labels_add"] or v["labels_remove"]]
    if labelled:
        out.append("\n## Label changes proposed\n")
        for number, add, remove in sorted(labelled):
            out.append("- #%d: +%s -%s" % (number, add, remove))

    live = [v for v in verdicts.values() if v.get("live_repro_design")]
    if live:
        out.append("\n## Live-repro queue (wave 2) (%d)\n" % len(live))
        for verdict in sorted(live, key=lambda v: v["n"]):
            design = verdict["live_repro_design"]
            result = verdict.get("live_repro")
            status = ("%d/%d reproduced, %d void"
                      % (result["reproduced"], result["reps"], result["void"])
                      if result else "pending")
            out.append("- #%d (%s, reps %s): %s — %s" % (
                verdict["n"], design["model"], design["reps"], status,
                design["decisive_observation"][:200]))

    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verdicts", required=True,
                        help="directory of per-issue verdict JSON files")
    parser.add_argument("--issues",
                        help="JSON from `gh issue list --json number,title`; supplies "
                             "titles and lets the report name issues with no verdict")
    parser.add_argument("--md", default="report.md",
                        help="markdown output (default: %(default)s)")
    parser.add_argument("--json", dest="json_out", default="verdicts.json",
                        help="merged machine-readable output (default: %(default)s)")
    parser.add_argument("--schema", default=SCHEMA_PATH,
                        help="verdict schema (default: the plugin's references copy)")
    parser.add_argument("--title", default="Issue triage report",
                        help="report heading (default: %(default)s)")
    parser.add_argument("--missing", action="store_true",
                        help="only report which open issues have no verdict file yet")
    args = parser.parse_args()

    if args.missing and not args.issues:
        parser.error("--missing needs --issues to know what the open issues are")

    with open(args.schema) as fh:
        schema = json.load(fh)

    issues = {}
    if args.issues:
        with open(args.issues) as fh:
            issues = {i["number"]: i for i in json.load(fh)}

    verdicts, errors = load_verdicts(args.verdicts, schema)

    if args.missing:
        missing = sorted(set(issues) - set(verdicts))
        print("%d/%d verdicts; missing: %s" % (len(verdicts), len(issues), missing))
        return 0

    if errors:
        for error in errors:
            sys.stderr.write("INVALID %s\n" % error)
        rejected = len(set(e.split(":")[0] for e in errors))
        sys.stderr.write("%d verdict file(s) rejected; wrote nothing.\n" % rejected)
        return 1

    with open(args.md, "w") as fh:
        fh.write(render(verdicts, issues, args.title))
    with open(args.json_out, "w") as fh:
        json.dump([verdicts[n] for n in sorted(verdicts)], fh, indent=1)

    counts = Counter(v["verdict"] for v in verdicts.values())
    print("%d verdicts -> %s, %s" % (len(verdicts), args.md, args.json_out))
    print({name: counts[name] for name in VERDICT_ORDER if counts.get(name)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
