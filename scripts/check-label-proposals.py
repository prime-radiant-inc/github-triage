#!/usr/bin/env python3
"""Check labeler subagents' label proposals against themselves and live GitHub state.

When to use: after labeler subagents following references/labeler-brief.md have written
their batch-*.json files, and before anything is shown to the maintainer or applied. Why:
cheap-model labelers contradict themselves -- a template_ignored flag set to true with the
label missing from add, a needs-rebase label on a PR that already targets dev -- and with
hundreds of items those slips are invisible by eye. This lists every contradiction, and
writes an apply-triage-actions.py actions file only once none remain. Fix a problem by
correcting the record in an --overrides file, which also records why you overruled the
labeler.

Usage:
  check-label-proposals.py --proposals DIR --issues issues.json --prs prs.json
      [--overrides overrides.json] [--exempt LOGIN,GLOB,...] [--retired LABEL,...]
      [--wrong-base main --rebase-label needs-rebase-to-dev]
      [--actions-out actions.json]

  --issues / --prs take the JSON from:
    gh issue list --repo OWNER/REPO --state open --limit 1000 --json number,author,labels
    gh pr list --repo OWNER/REPO --state open --limit 1000 \\
        --json number,author,labels,baseRefName

Overrides file: {"2511": {"add": ["windows"], "no_human_review": false,
                          "verifier": "honest limitations; not flagging"}}
  Each key replaces that field of the labeler's record before any check runs. The merged
  record must still match the schema, and an override for an item no labeler proposed is
  a problem: a correction that silently lands nowhere defeats the point of making it.

--exempt lists authors (fnmatch globs allowed, e.g. maintainer,*-bot) whose items never
carry the review or template labels: proposed ones are dropped and existing ones removed,
and both are reported rather than flagged. The label names are fixed:
no-obvious-human-review, issue-template-rules-ignored, pr-template-rules-ignored.

The actions file holds action "keep" entries with only the real changes: labels the item
lacks in labels_add, labels it has in labels_remove. Apply it with
  apply-triage-actions.py --repo OWNER/REPO --actions actions.json --only-labels \\
      --approved <the numbers the maintainer approved> --identity identity.json

Exit status: 0 clean, 1 contradictions found (nothing written), 2 unreadable input.
"""
import argparse
import fnmatch
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(os.path.dirname(HERE), "references", "label-proposal-schema.json")

REVIEW_LABEL = "no-obvious-human-review"
TEMPLATE_LABELS = {"issue": "issue-template-rules-ignored", "pr": "pr-template-rules-ignored"}
FLAG_LABELS = {REVIEW_LABEL} | set(TEMPLATE_LABELS.values())


def load_validator():
    """build-report.py owns the schema-subset validator; load it rather than copy it."""
    spec = importlib.util.spec_from_file_location(
        "build_report", os.path.join(HERE, "build-report.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("%s: %s\n" % (path, exc))
        sys.exit(2)


def load_proposals(directory, overrides):
    """Return (records, problems): every record from DIR/batch-*.json with overrides
    applied, each schema-checked before and after; problems are records that would
    otherwise vanish silently."""
    validate = load_validator()
    schema = read_json(SCHEMA_PATH)
    paths = sorted(glob.glob(os.path.join(directory, "batch-*.json")))
    if not paths:
        sys.stderr.write("%s: no batch-*.json files\n" % directory)
        sys.exit(2)
    records, problems, seen, broken = [], [], {}, False
    for path in paths:
        batch = read_json(path)
        errors = validate(batch, schema)
        if errors:
            broken = True
            sys.stderr.write("%s:\n  %s\n" % (path, "\n  ".join(errors)))
            continue
        for record in batch:
            number = record["number"]
            if number in seen:
                problems.append("#%d: proposed in both %s and %s"
                                % (number, seen[number], os.path.basename(path)))
                continue
            seen[number] = os.path.basename(path)
            records.append(record)
    if broken:
        sys.exit(2)
    for key in sorted(set(overrides) - {str(n) for n in seen}, key=int):
        problems.append("#%s: override matches no proposal" % key)
    for record in records:
        record.update(overrides.get(str(record["number"]), {}))
        errors = validate(record, schema["$defs"]["proposal"], schema)
        if errors:
            broken = True
            sys.stderr.write("override for #%d:\n  %s\n"
                             % (record["number"], "\n  ".join(errors)))
    if broken:
        sys.exit(2)
    return sorted(records, key=lambda r: r["number"]), problems


def live_state(issues_path, prs_path):
    """number -> (kind, author, set of labels, base branch or None)."""
    state = {}
    for kind, path in (("issue", issues_path), ("pr", prs_path)):
        try:
            for item in read_json(path):
                state[item["number"]] = (kind, item["author"]["login"],
                                         {label["name"] for label in item["labels"]},
                                         item.get("baseRefName"))
        except (KeyError, TypeError) as exc:
            sys.stderr.write("%s: not gh list JSON with number, author and labels "
                             "(missing %s)\n" % (path, exc))
            sys.exit(2)
    return state


def check(record, live, args):
    """Return (problems, notes, labels_add, labels_remove) for one record."""
    number, kind = record["number"], record["kind"]
    if number not in live or live[number][0] != kind:
        return ["#%d: not an open %s" % (number, kind)], [], [], []
    _, author, current, base = live[number]
    add, remove = set(record["add"]), set(record["remove"])
    notes = []

    if any(fnmatch.fnmatchcase(author, pattern) for pattern in args.exempt):
        dropped = sorted((add | current) & FLAG_LABELS)
        add -= FLAG_LABELS
        remove |= current & FLAG_LABELS
        flags = dict(record, no_human_review=False, template_ignored=False)
        if dropped:
            notes.append("#%d: exempt author %s, dropped %s"
                         % (number, author, ", ".join(dropped)))
    else:
        flags = record

    after = (current - remove) | add
    problems = []
    template_label = TEMPLATE_LABELS[kind]
    wrong_kind = TEMPLATE_LABELS["pr" if kind == "issue" else "issue"]
    if wrong_kind in after:
        problems.append("#%d: %s on an %s" % (number, wrong_kind, kind))
    for flag, label in (("template_ignored", template_label),
                        ("no_human_review", REVIEW_LABEL)):
        if flags[flag] and label not in after:
            problems.append("#%d: %s is true but %s is not applied" % (number, flag, label))
        if not flags[flag] and label in add:
            problems.append("#%d: %s is applied but %s is false" % (number, label, flag))
    for label in sorted(after & set(args.retired)):
        problems.append("#%d: retired label still applied: %s" % (number, label))
    # Keyed to the one wrong base, not "anything but dev": stacked PRs legitimately
    # target feature branches.
    if kind == "pr" and args.wrong_base:
        if base == args.wrong_base and args.rebase_label not in after:
            problems.append("#%d: base is %s but %s is not applied"
                            % (number, base, args.rebase_label))
        if base != args.wrong_base and args.rebase_label in after:
            problems.append("#%d: base is %s, not %s, but %s is applied"
                            % (number, base, args.wrong_base, args.rebase_label))
    return problems, notes, sorted(add - current), sorted(remove & current)


def split_list(text):
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proposals", required=True, metavar="DIR",
                        help="directory of labeler batch-*.json files")
    parser.add_argument("--issues", required=True, metavar="FILE",
                        help="open issues JSON (see above)")
    parser.add_argument("--prs", required=True, metavar="FILE",
                        help="open PRs JSON (see above)")
    parser.add_argument("--overrides", metavar="FILE",
                        help="your verified corrections, keyed by item number")
    parser.add_argument("--exempt", type=split_list, default=[], metavar="LOGIN,GLOB,...",
                        help="authors who never get review or template labels")
    parser.add_argument("--retired", type=split_list, default=[], metavar="LABEL,...",
                        help="labels being migrated away; none may remain on an item")
    parser.add_argument("--wrong-base", metavar="BRANCH",
                        help="branch PRs must not target (e.g. main when work lands on "
                             "dev); enables the rebase-label check")
    parser.add_argument("--rebase-label", metavar="LABEL",
                        help="label for PRs targeting --wrong-base; required with it")
    parser.add_argument("--actions-out", metavar="FILE",
                        help="write the actions file here when there are no problems")
    args = parser.parse_args()
    if args.wrong_base and not args.rebase_label:
        parser.error("--wrong-base needs --rebase-label (the label the taxonomy uses)")

    overrides = read_json(args.overrides) if args.overrides else {}
    records, problems = load_proposals(args.proposals, overrides)
    live = live_state(args.issues, args.prs)

    notes, actions = [], {}
    unproposed = len(set(live) - {r["number"] for r in records})
    if unproposed:
        notes.append("%d open items have no proposal" % unproposed)
    for record in records:
        found, noted, labels_add, labels_remove = check(record, live, args)
        problems += found
        notes += noted
        if labels_add or labels_remove:
            actions[str(record["number"])] = {
                "action": "keep", "labels_add": labels_add, "labels_remove": labels_remove}

    for line in notes + problems:
        print(line)
    if problems:
        print("%d problem(s) in %d proposals; fix them in an overrides file. "
              "No actions file written." % (len(problems), len(records)))
        return 1

    print("%d proposals clean; %d items change." % (len(records), len(actions)))
    if args.actions_out:
        with open(args.actions_out, "w") as fh:
            json.dump({"issues": actions}, fh, indent=2)
        print("wrote %s" % args.actions_out)
        print("--approved %s" % ",".join(sorted(actions, key=int)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
