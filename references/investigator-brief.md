# Open-issue triage — investigator protocol

> Template. Fill the six placeholders before handing this to an investigator:
> `{{repo}}` (owner/name), `{{checkout_path}}` (a local checkout to read),
> `{{branch}}` (the branch that is current truth), `{{baseline_commit}}` (what a prior
> triage was measured against, or the release the reporters are on),
> `{{prior_triage_path}}` (previous triage output, or "none"), and `{{output_dir}}`
> (where hints, verdicts and live-session logs go). Give every investigator the same
> filled copy.

You are investigating a small batch of OPEN ISSUES on `{{repo}}` for the maintainer. For
each issue, answer ONE question: **does the behavior the reporter describes still occur
on `{{branch}}`?** For feature requests: **is the user need still unmet?** You answer by
testing, never by trusting prose.

A bug report is a hypothesis from an unreliable narrator. Reporters misdiagnose root
causes, point at the wrong file, describe environment-specific behavior as universal, and
sometimes describe things that never happened. The file the reporter cited still
containing the line they quoted proves NOTHING about whether the bug exists. Run the
scenario. Verify the behavior, not the theory.

## Ground truth and tools

- Current code truth: `{{checkout_path}}`, branch `{{branch}}`. **READ ONLY.** Never
  modify it, commit to it, or switch its branches. `git -C {{checkout_path}}
  log/show/grep/diff` freely. `git -C {{checkout_path}} diff
  {{baseline_commit}}..{{branch}} -- <path>` shows what changed for any file an issue
  cites since the baseline.
- Issue data: `gh issue view N --repo {{repo}} --json title,body,comments,labels,author,createdAt`.
  Read the FULL body and ALL comments — maintainer replies often settle things.
- Related PRs: `gh pr list --repo {{repo}} --state all --search '<terms>' --json number,title,state,baseRefName`.
  An open PR that fixes the issue is a fact worth reporting; read its diff and check it
  does what it says.
- Duplicates: `gh issue list --repo {{repo}} --state all --search '<terms>' --json number,title,state`.
  Name numbers. The earlier, better-evidenced, or maintainer-engaged one is canonical.
- Repo policy: read the repo's own `CLAUDE.md` / `CONTRIBUTING.md` before calling
  anything out of scope. What the maintainers have already said no to is evidence.
- Scratch space: `mktemp -d` only. Never write inside any repo checkout. Never use
  recursive-delete flags; leave temp dirs in place.
- Never run `git worktree add/remove/prune` against `{{checkout_path}}`. If you need a
  mutable copy: `git clone {{checkout_path}} <tmp>/repo`.

## Hint files

`{{output_dir}}/hints/<n>.md` holds the issue title, its current labels, a claim-type
classification, a suggested first test, and — when the issue appears in
`{{prior_triage_path}}` — the verdict and summary from that earlier pass.

**A prior verdict is a prior, not an answer.** Its evidence was gathered against
`{{baseline_commit}}`. Re-verify the load-bearing claim on `{{branch}}` before you inherit
its conclusion.

## Wave 1 rule: no live agent sessions

Wave 1 is static only. Do not run `claude`, `claude -p`, or any LLM session. Do not
dispatch subagents.

When an issue's load-bearing claim is about live agent behavior — the model does X when
given skill Y — do all the static work you can: is the text the reporter blames present,
changed, or gone; do the cited lines exist; is there an open PR. Then set verdict
`NEED_LIVE_REPRO` and attach a `live_repro_design`: what the fixture must contain, the
neutral user prompt, the cheapest model that could settle it, the single decisive
observation, and how many reps. Wave 2 runs it.

Two waves exist because live sessions cost real money and most issues do not need one.
Doing the cheap work first tells you exactly which issues do.

## What to test, by claim type

- **Deterministic** (shell scripts, hooks, plugin manifests, CSS, tests, YAML, git
  behavior): construct the inputs the reporter describes in a temp dir, run the actual
  code path from the checkout, observe. Quote the output. This is the one category you
  can settle outright.
- **Environment-specific** (a named OS, harness, or toolchain you do not have): first ask
  whether the claim is actually environment-specific or only described that way — a path
  bug may reproduce anywhere. For open-source tools, read their source to verify the
  reporter's claims about how they behave. If you still cannot settle it, verdict
  `NEED_REPRO_ENV` and name the environment and the exact test.
- **Text and design claims** ("the docs say X, which causes Y"): quote the current text
  on `{{branch}}` with line numbers. Distinguish: (a) the text is gone or changed, so the
  claim may be moot; (b) the text is there and the claimed consequence is a deterministic
  reading; (c) the consequence is a model-behavior claim, which means `NEED_LIVE_REPRO`.
- **Feature requests**: "is this need still unmet?" Search synonyms — the implementer may
  have named it differently. A request can be valid even if a related feature exists; it
  can be invalid if the need is met under another name.
- **Slop and spam**: only with quotable evidence — fabricated paths, hallucinated APIs,
  nothing about this repo. The word is an accusation; carry the receipts.

Tempting shortcuts that produce wrong verdicts. Do not take them:

- "The cited line is unchanged, so the bug is still valid." Run the scenario.
- "A commit on `{{branch}}` mentions this issue number, so it's fixed." Verify the
  behavior is gone. Commit messages can lie, or fix a different aspect of the same bug.
- "grep returned 0 results, so it's not implemented." Try synonyms.
- "The reporter said it happens on another platform, so it's uncertain." Check whether the
  claim is really platform-specific before you shelve it.

## Verdict taxonomy

Pick exactly one. These are the values `references/verdict-schema.json` accepts.

| Verdict | Meaning |
|---|---|
| `REPRODUCED` | You followed the steps and observed the behavior on `{{branch}}` |
| `NOT_REPRODUCIBLE` | You followed the steps; the behavior did not occur. Say what you did |
| `NEED_LIVE_REPRO` | Static work done; settling it needs a live agent session (design attached) |
| `NEED_REPRO_ENV` | Needs an environment you do not have; name it and the exact test |
| `NEED_MORE_INFO` | The report lacks enough detail to attempt anything; say what is missing |
| `FEATURE_UNMET` | Feature request; the need is real and still unmet |
| `FEATURE_MET` | Feature request; the need is met (name how) |
| `RESOLVED_ON_MAIN` | Bug fixed on `{{branch}}`; name the commits and show the behavior is gone |
| `RESOLVED_BY_OPEN_PR` | An open PR fixes it; give the number, and read the diff |
| `DUPLICATE` | Same problem as an earlier open issue; name the canonical one and why |
| `OPINION_NOT_BUG` | Works as designed; quote the design intent it conflicts with |
| `WRONG_VENUE` | Real, but belongs to another project or tracker |
| `NEEDS_MAINTAINER_DECISION` | Facts verified, judgment genuinely contested; lay out both sides |
| `SLOP` | Fabricated, or nothing to do with this repo; quoted evidence |

`confidence` is `high`, `medium` or `low` — how sure you are AFTER your tests, not before.

## Wave 2: live reproduction

Wave 2 runs only the designs wave 1 attached. Your input is each issue's
`live_repro_design`; your output is the same verdict file, rewritten with the question
settled and the evidence attached.

Workers are real agent sessions driven through a session driver. For each rep: build the
fixture from the design in a fresh directory, launch a worker there with the model the
design names, send the design's prompt, read the full turn back including tool results,
then stop the worker.

- **The model tier is the cost lever.** Run the model the design names — the cheapest one
  that could settle the question. Never a larger one because it is convenient.
- **One fixture directory per rep**, built fresh, under `{{output_dir}}` only. Never
  launch a worker with its working directory inside a real repository or inside
  `{{checkout_path}}`. Workers can write anywhere under their working directory.
- **Rep cap: 3 per issue.** Run one. If the outcome is ambiguous or contradicts the claim,
  run up to two more. Stop early when it is decisive.
- **Neutral prompt.** Use the design's `prompt` verbatim unless it hints at the expected
  failure — in which case fix it and record exactly what you changed.
- **Note the confounds.** Installed plugins, global instruction files and shell
  configuration load in every worker. If any of them plausibly bears on the observation,
  say so in `notes`.
- **Save every rep** to `{{output_dir}}/live/<n>/rep<k>.md`: the prompt, the full turn,
  and the list of tool calls. Quote the decisive lines in the verdict's evidence.
- **Always stop the worker**, including on failure.
- A rep reproduces when the design's `decisive_observation` occurs, and does not when the
  agent does the right thing. A timeout, a refusal, or an unrelated failure is a **void**
  rep — it is not a result. Run another if you have reps left.
- Report reps honestly. `2/3` is a finding and so is `0/3`. Do not round.

## Output

Write `{{output_dir}}/verdicts/<n>.json`, one file per issue.

**The shape and every allowed value are defined by `references/verdict-schema.json` in
the github-triage plugin. Read it and conform exactly** — `scripts/build-report.py`
validates each file against it and rejects the entire run if any file is wrong.

- Every load-bearing assertion in the issue gets one `evidence` entry: `claim` (the
  assertion), `test` (the exact command or reading, so it can be re-run), `result` (what
  you observed — quotes over paraphrase).
- `summary` is at most 60 words: what the issue is, what you found, what the maintainer
  should do.
- `draft_reply` is 2–6 sentences the maintainer could paste: specific, evidence-based,
  kind to good-faith reporters, firm on slop, and free of timelines. Empty when no reply
  is warranted.
- `recommended_action` of `keep`, `comment` or `close` feeds the actions file that
  `scripts/apply-triage-actions.py` consumes. Use `needs-maintainer` when the call is not
  yours to make.
- Wave 2 additionally fills `live_repro` and updates `verdict`, `summary`,
  `recommended_action` and `draft_reply` to match the outcome.

Return one line per issue: `#n VERDICT (confidence) — ten words`. Nothing else. The JSON
files are the deliverable.
