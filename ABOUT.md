# github-triage

> Claude Code plugin for triaging GitHub issues and pull requests, with a security-gated PR review workflow.

**Family:** bots · **Type:** tool · **Lifecycle:** production · **Owner:** obra

## What it does
github-triage is a Claude Code plugin for systematic GitHub issue and PR triage. Its `github-triage` skill runs a seven-phase workflow: discover patterns, propose a label taxonomy, create labels, tag issues/PRs, summarize, validate open issues against the codebase, and run a security-gated PR review. The bundled `pr-security-review` agent is a read-only security analysis agent (Read/Grep/Glob/WebFetch only) that screens PR diffs for malware, supply-chain attacks, credential theft, CI/CD poisoning, and test weaponization before any local checkout.

## How it fits
- Depends on: — (a Claude Code plugin; no package manifest or internal code dependencies)
- Used by: — (installed into Claude Code via the plugin marketplace)
- External: GitHub (issues/PRs), Claude Code runtime.

## Runtime & data
- Runs: Claude Code plugin (skill + agent); not a deployed service.
- Data in: GitHub issues, PRs, and diffs.
- Data out: labels, triage summaries, PR review/merge actions.

<!-- Maintained by the maintaining-project-map skill. Do not hand-edit; regenerated. -->
