# github-triage

A Claude Code plugin for systematic GitHub issue and PR triage, with a security-gated PR review workflow.

## Components

### Skill: `github-triage`

Full triage workflow across 7 phases:
- **Phase 1–5**: Discover patterns, propose label taxonomy, create labels, tag issues/PRs, summarize
- **Phase 6**: Validate open issues against the codebase (oldest-first), close resolved ones with evidence — at scale, via the two-wave protocol the scripts and references below support
- **Phase 7**: Security-gated PR review — security analysis → parallel code review + local tests → merge + author credit

### Agent: `github-triage:pr-security-review`

Read-only security analysis agent (tools: Read, Grep, Glob, WebFetch — no execution, no writes).

Analyzes PR diffs before any local code checkout for:
- Malware and backdoors
- Supply chain attacks and typosquatting
- Credential theft and data exfiltration
- CI/CD and build script poisoning
- Test weaponization

Returns: ✅ SAFE / ⚠️ REVIEW NEEDED / 🚫 BLOCK

### Scripts

Python 3 standard library only — no pip dependencies. `gh` is the only external tool.

| Script | What it does |
|--------|--------------|
| `scripts/build-report.py` | Merges per-issue verdict files into `report.md` + `verdicts.json`, validating each against `references/verdict-schema.json` first and writing nothing if any file is malformed. `--missing` reports which open issues still have no verdict. |
| `scripts/apply-triage-actions.py` | Applies an approved actions file: creates only the labels the file declares, refuses to apply a label that doesn't exist in the repo (`gh issue edit --add-label` would silently create it), posts identity-disclosed comments, closes. Has `--dry-run`, `--only-labels`, and an `--approved` list it will not act outside of. |

Both print their input-file shapes under `--help`.

```bash
scripts/build-report.py --verdicts verdicts/ --issues issues.json --title "Acme triage"

scripts/apply-triage-actions.py --repo acme/widget --actions actions.json \
    --approved 1860,2211 --identity identity.json --dry-run
```

A verdict's `recommended_action`, `labels_add`, `labels_remove` and `draft_reply` are what
you filter and rename into the actions file's `action`, `labels_add`, `labels_remove` and
`reply`. Nothing goes from a report to GitHub without a human choosing the issue numbers.

### References

| File | What it is |
|------|------------|
| `references/verdict-schema.json` | JSON Schema for one triage verdict — the contract between investigator agents and `build-report.py`. |
| `references/investigator-brief.md` | Template for the protocol handed to investigator subagents: the skepticism rules, the claim-type test matrix, the verdict taxonomy, and the wave-1 / wave-2 split. Fill in six `{{placeholders}}`. |

## Tests

```bash
tests/run-tests.sh
```

Standard-library `unittest`, no network, no real `gh`. A fake `gh` on `PATH` records every
argument the scripts pass it, so label safety, refusals, dry runs, comment bodies and exit
codes are all asserted at the real subprocess boundary.

## Installation

```bash
claude plugin marketplace add /path/to/github-triage --name github-triage-dev
claude plugin install github-triage@github-triage-dev
```

## Usage

Use the `github-triage` skill for full triage sessions, or invoke `github-triage:pr-security-review` directly via the Task tool before checking out PR code.

The scripts run standalone from a checkout of this plugin, or from its installed copy under `~/.claude/plugins/`. They need no setup beyond `gh` being authenticated.
