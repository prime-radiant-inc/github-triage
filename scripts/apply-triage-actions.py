#!/usr/bin/env python3
"""Apply a maintainer-approved set of triage actions to GitHub issues.

When to use: after the maintainer has reviewed a triage report and approved a specific
list of issue numbers. Why: `gh issue edit --add-label` silently creates any label that
does not exist, which quietly corrupts a label taxonomy, and a half-applied run across a
hundred issues is painful to undo. This script creates only the labels the actions file
declares, verifies every label it is about to apply or remove already exists, refuses any
issue the maintainer did not approve, and does all of that before it makes a single
mutating call. Comments carry an identity preamble naming the model, the harness and the
session, and a footer inviting the reporter to push back.

Usage:
  apply-triage-actions.py --repo OWNER/REPO --actions actions.json \\
      --approved 1860,2211,2222 --identity identity.json [--dry-run] [--only-labels]

Actions file:
  {"new_labels": {"hermes": {"color": "5319e7", "description": "Hermes Agent"}},
   "issues": {"1860": {"labels_add": ["bug"], "labels_remove": ["needs-triage"],
                       "action": "close", "reply": "Duplicate of #809 ..."}}}

  action is one of keep | comment | close. close and comment need a non-empty reply;
  keep applies labels only. Per issue the order is labels first, then the action.
  Labels under new_labels are created only if some approved issue actually wants them.

Identity (file keys, each overridable by the matching flag):
  model, harness, session_url, maintainer, maintainer_name
  model, harness and maintainer are required. session_url is dropped from the footer if
  absent, which beats leaving a blank placeholder. Discover the session id with:
    ps -p $PPID -o args= | grep -oE -- '--session-id [^ ]+' | awk '{print $2}'

One line per action on stdout; every gh command and its full output go to the log file.
Exits non-zero on the first gh failure, leaving the remaining issues untouched.
"""
import argparse
import json
import os
import subprocess
import sys

ACTIONS = ("keep", "comment", "close")

REPORTER_PREAMBLE = (
    "Hi @{author} — I'm Claude, an AI agent ({model}, running in {harness}), posting "
    "from {maintainer_ref}'s account at their direction. "
    "{maintainer_name} reviewed the finding below and approved this {kind}.\n\n"
)
MAINTAINER_PREAMBLE = (
    "Triage note from Claude, an AI agent ({model}, running in {harness}), posting from "
    "{maintainer_name}'s own account at their direction after they reviewed this "
    "finding.\n\n"
)
FOOTER = (
    "\n\n---\n*If any of the evidence above is wrong, reply here — {maintainer_name} "
    "reads these, and decisions can be revisited.*\n\n— {model}, {harness}{session}"
)


class GhError(RuntimeError):
    pass


class Gh(object):
    """Runs gh, mirroring every command and its full output into the log file."""

    def __init__(self, log_path, dry_run):
        self.log_path = log_path
        self.dry_run = dry_run

    def _log(self, text):
        with open(self.log_path, "a") as fh:
            fh.write(text)

    def run(self, *args, **kwargs):
        """Run `gh <args>`. Calls that change state are skipped under --dry-run."""
        mutating = kwargs.pop("mutating", True)
        cmd = ["gh"] + list(args)
        skip = self.dry_run and mutating
        self._log(("DRY " if skip else "") + " ".join(cmd) + "\n")
        if skip:
            return ""
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self._log(proc.stdout + proc.stderr + "\n")
        if proc.returncode != 0:
            raise GhError("gh failed (%d): %s\n%s"
                          % (proc.returncode, " ".join(cmd[:5]), proc.stderr.strip()))
        return proc.stdout


def load_identity(args, parser):
    """Merge the identity file with the individual flags; flags win."""
    identity = {}
    if args.identity:
        with open(args.identity) as fh:
            identity = json.load(fh)
    for key in ("model", "harness", "session_url", "maintainer", "maintainer_name"):
        value = getattr(args, key, None)
        if value:
            identity[key] = value
    missing = [k for k in ("model", "harness", "maintainer") if not identity.get(k)]
    if missing:
        parser.error("identity is incomplete: %s (give --identity FILE or the flags)"
                     % ", ".join(missing))
    identity.setdefault("maintainer_name", "@" + identity["maintainer"])
    identity.setdefault("session_url", "")
    return identity


def build_body(reply, author, identity, kind):
    """Identity preamble + the approved reply + the revisit footer."""
    handle = "@" + identity["maintainer"]
    # "Ada (@ada-l)" when there is a name to give, plain "@ada-l" when the name IS the
    # handle -- otherwise the default maintainer_name renders the handle twice.
    reference = (handle if identity["maintainer_name"] == handle
                 else "%s (%s)" % (identity["maintainer_name"], handle))
    fields = dict(identity, author=author, kind=kind, maintainer_ref=reference)
    preamble = (MAINTAINER_PREAMBLE if author == identity["maintainer"]
                else REPORTER_PREAMBLE)
    session = (", session " + identity["session_url"]) if identity["session_url"] else ""
    return (preamble.format(**fields) + reply.strip()
            + FOOTER.format(session=session, **fields))


def parse_actions(path, approved, parser):
    """Return (new_labels, [(number, entry)]) for the approved issues, or exit."""
    with open(path) as fh:
        document = json.load(fh)
    entries = document.get("issues") or {}
    unknown = [n for n in approved if str(n) not in entries]
    if unknown:
        parser.error("approved issues absent from %s: %s" % (path, unknown))
    selected = [(n, entries[str(n)]) for n in approved]
    for number, entry in selected:
        action = entry.get("action")
        if action not in ACTIONS:
            parser.error("#%d: action %r is not one of %s"
                         % (number, action, ", ".join(ACTIONS)))
        if action in ("close", "comment") and not (entry.get("reply") or "").strip():
            parser.error("#%d: action %r needs a non-empty reply" % (number, action))
    return document.get("new_labels") or {}, selected


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, metavar="OWNER/REPO")
    parser.add_argument("--actions", required=True, metavar="FILE",
                        help="approved per-issue actions (see the shape above)")
    parser.add_argument("--approved", required=True, metavar="N,N,...",
                        help="the issue numbers the maintainer approved; anything else "
                             "in the actions file is left alone")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would happen and make no mutating gh call")
    parser.add_argument("--only-labels", action="store_true",
                        help="apply label changes only; post no comments, close nothing")
    parser.add_argument("--log", default="apply-triage-actions.log",
                        help="full gh transcript (default: %(default)s)")
    parser.add_argument("--identity", metavar="FILE",
                        help="JSON with model, harness, session_url, maintainer, "
                             "maintainer_name")
    parser.add_argument("--model", help="e.g. 'Claude Opus 5'")
    parser.add_argument("--harness", help="e.g. 'Claude Code 2.1.259'")
    parser.add_argument("--session-url", dest="session_url",
                        help="session permalink; omitted from the footer if absent")
    parser.add_argument("--maintainer", help="the maintainer's GitHub login")
    parser.add_argument("--maintainer-name", dest="maintainer_name",
                        help="how to name the maintainer in prose (default: @login)")
    args = parser.parse_args()

    try:
        approved = [int(x) for x in args.approved.split(",") if x.strip()]
    except ValueError:
        parser.error("--approved takes comma-separated issue numbers")
    if not approved:
        parser.error("--approved is empty; nothing to do")

    identity = load_identity(args, parser)
    new_labels, selected = parse_actions(args.actions, approved, parser)

    gh = Gh(args.log, args.dry_run)
    try:
        existing = {label["name"] for label in json.loads(gh.run(
            "label", "list", "--repo", args.repo, "--json", "name", "--limit", "500",
            mutating=False))}
    except GhError as exc:
        sys.stderr.write("%s\n" % exc)
        return 1

    wanted = set()
    for _, entry in selected:
        wanted |= set(entry.get("labels_add") or [])
        wanted |= set(entry.get("labels_remove") or [])
    unknown = sorted(wanted - existing - set(new_labels))
    if unknown:
        sys.stderr.write(
            "REFUSING: labels not in %s and not declared under new_labels: %s\n"
            % (args.repo, unknown))
        return 1

    done = {"created": 0, "labels": 0, "comment": 0, "close": 0}
    try:
        for name in sorted(set(new_labels) & wanted):
            if name in existing:
                continue
            spec = new_labels[name]
            print("create label: %s" % name)
            gh.run("label", "create", name, "--repo", args.repo,
                   "--color", spec["color"], "--description", spec["description"])
            existing.add(name)
            done["created"] += 1

        for number, entry in selected:
            add = entry.get("labels_add") or []
            remove = entry.get("labels_remove") or []
            if add or remove:
                command = ["issue", "edit", str(number), "--repo", args.repo]
                if add:
                    command += ["--add-label", ",".join(add)]
                if remove:
                    command += ["--remove-label", ",".join(remove)]
                print("#%d: labels +%s -%s" % (number, ",".join(add), ",".join(remove)))
                gh.run(*command)
                done["labels"] += 1

            action = entry["action"]
            if action == "keep" or args.only_labels:
                continue

            author = json.loads(gh.run(
                "issue", "view", str(number), "--repo", args.repo, "--json", "author",
                mutating=False))["author"]["login"]
            body = build_body(entry["reply"], author, identity,
                              "closure" if action == "close" else "reply")
            if action == "close":
                print("#%d: CLOSE (reply to @%s)" % (number, author))
                gh.run("issue", "close", str(number), "--repo", args.repo,
                       "--reason", "not planned", "--comment", body)
            else:
                print("#%d: COMMENT (reply to @%s)" % (number, author))
                gh.run("issue", "comment", str(number), "--repo", args.repo,
                       "--body", body)
            done[action] += 1
    except GhError as exc:
        sys.stderr.write("%s\nStopped. Log: %s\n" % (exc, args.log))
        return 1

    print("\n%s%s. Log: %s" % ("DRY RUN: " if args.dry_run else "", done, args.log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
