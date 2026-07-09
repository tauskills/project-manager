---
name: skill-project-manager
description: Unified governance skill for project managers and AI advisors. Use when work needs stage-gate checks across PRD review, release readiness, project milestone risk, or similar project-governance tasks tied to issue threads and docs folders. Current P1 implementation includes runnable `prd-qa-checker` and `release-readiness-checker` modules plus a shared normalized gate code contract for automation.
---

# Skill Project Manager

## Overview

Use this skill when a project manager, AI advisor, or cross-functional owner needs one entrypoint for governance checks across product, development, QA, and release stages.

Current scope:

- P1 live module: `prd-qa-checker`
- P1 live module: `release-readiness-checker`
- P2 planned modules: `api-contract-guard`, `design-dev-diff-checker`

This repository is the canonical maintenance location for this skill.

## Module Routing

Choose module by input artifact:

- PRD Markdown under `docs/product/`: use `prd-qa-checker`
- Release record under `docs/release/`: use `release-readiness-checker`
- API contract alignment review: do not automate here yet; use manual playbook later
- Design vs implementation diff review: do not automate here yet; use manual playbook later

If user asks for generic "project management check", inspect supplied doc path first, then choose module from artifact type rather than guessing from prose alone.

## Deterministic Artifact Paths

Use fixed repo paths so inputs and checker outputs are easy to find and can be referenced from issue comments without extra explanation.

| Artifact | Canonical path | Naming rule |
| --- | --- | --- |
| PRD source | `docs/product/` | one requirement per Markdown file |
| PRD QA report | `docs/review/prd-qa/` | `{prd-file-stem}.prd-qa.generated.md` |
| Release record source | `docs/release/` | one release record per Markdown file |
| Release readiness report | `docs/review/release-readiness/` | `{release-file-stem}.release-readiness.generated.md` |

Rules:

- If the workspace does not yet have these directories, create them before first use.
- Prefer stable file stems derived from the business artifact, for example `wallet-withdraw-v2.md` or `2026-07-15-wallet-hotfix.md`.
- Keep checker output under `docs/review/...`; do not scatter reports into temp folders, downloads, or issue attachments only.
- When pasting checker conclusions into an issue, include the durable repo path.

## `prd-qa-checker`

Use when:

- PRD follows or roughly follows the team's PRD template structure
- Team needs gate advice before design review, technical solutioning, or QA planning
- CEO / PM / product owner needs a report that can be pasted into an issue comment

Run path:

```bash
python3 scripts/prd_qa_checker.py \
  --prd docs/product/your-prd.md \
  --issue WAR-342 \
  --output auto
```

Default behavior:

- Reads PRD Markdown
- Checks template completeness and governance gaps
- Produces Markdown report to stdout
- Supports `--output <path>` to save durable report
- Supports `--output auto` to save to `docs/review/prd-qa/{prd-file-stem}.prd-qa.generated.md`

Before running, read [`references/prd-qa-checker.md`](references/prd-qa-checker.md) for:

- rule coverage
- severity model
- output contract
- limits of automated judgment

## `release-readiness-checker`

Use when:

- release record roughly follows the team's release record template
- project manager / CTO / DevOps needs a pre-release gate recommendation
- team needs a paste-ready release comment before entering release-window review

Run path:

```bash
python3 scripts/release_readiness_checker.py \
  --release docs/release/your-release-record.md \
  --issue WAR-346 \
  --output auto
```

Default behavior:

- reads release record Markdown
- checks release gates, version/env clarity, change registration, rollback, monitoring, and smoke inputs
- produces Markdown report to stdout
- supports `--output <path>` to save durable report
- supports `--output auto` to save to `docs/review/release-readiness/{release-file-stem}.release-readiness.generated.md`

Before running, read [`references/release-readiness-checker.md`](references/release-readiness-checker.md) for:

- rule coverage
- severity model
- output contract
- limits of automated judgment

## Output Contract

Preferred output shape:

1. module decision:
   - PRD: `ALLOW_TO_REVIEW`, `REVISE_BEFORE_REVIEW`, or `BLOCK`
   - Release: `允许发布`, `有条件允许发布`, or `不允许发布`
2. normalized decision code: `allow`, `revise`, or `block`
3. risk level: `low`, `medium`, `high`
4. passed checks
5. missing or weak items with concrete repair advice
6. paste-ready issue comment

Keep conclusions concrete. Do not claim business correctness; judge document readiness only.

## Guardrails

- Treat this skill as governance automation, not product decision authority.
- If PRD deviates heavily from template, say coverage is partial and lower confidence.
- Do not invent missing requirements. Flag gap, explain why it blocks downstream teams.
- For API contracts and design diff, do not pretend implementation exists yet.
- For release readiness, final go/no-go remains with DevOps / CTO even when the checker says ready.

## Resources

- [`references/prd-qa-checker.md`](references/prd-qa-checker.md): live P1 rules
- [`references/release-readiness-checker.md`](references/release-readiness-checker.md): live P1 rules
- [`references/prd-example-input.md`](references/prd-example-input.md): sample input
- [`references/prd-example-report.md`](references/prd-example-report.md): sample output
- [`scripts/prd_qa_checker.py`](scripts/prd_qa_checker.py): runnable checker
- [`references/release-example-input.md`](references/release-example-input.md): sample release record
- [`references/release-example-report.generated.md`](references/release-example-report.generated.md): generated release report
- [`scripts/release_readiness_checker.py`](scripts/release_readiness_checker.py): runnable checker
