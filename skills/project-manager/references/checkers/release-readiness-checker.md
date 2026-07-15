# Release Readiness Checker

## Status

P1 live module. Implemented in `scripts/release_readiness_checker.py`.

## Purpose

Check whether a release record is complete enough for release-window review.

## Input Contract

- release record Markdown
- canonical location `docs/release/{date}-{issue-key}-{slug}/`
- version / milestone identifier
- optional environment list

Recommended durable output path:

- `docs/review/release-readiness/{release-file-stem}.release-readiness.generated.md`

Best effort support:

- release records that roughly follow [Release Record Template](../templates/release-record-template.md)
- Markdown headings with Chinese section names

Lower-confidence cases:

- freeform release notes without stable headings
- release evidence stored only in screenshots or chat logs
- teams that omit tables and keep all information in prose

## Rule Set

### High-risk checks

- gate conclusions from QA / product / engineering
- rollback steps
- rollback trigger conditions
- monitoring owner and observation window

High-risk failures usually mean `不允许发布` or at least `有条件允许发布`.

### Medium-risk checks

- version and environment clarity
- config and env-var registration
- migration / static asset impact
- release steps
- smoke registration

### Low-risk checks

- weak metadata hygiene
- weak change registration details that do not block execution

## Decision Logic

- `不允许发布`: 2 个或以上 high-risk 缺项，或门禁结论 / 回滚步骤缺失
- `有条件允许发布`: 1 个 high-risk 缺项，或 3 个或以上 medium-risk 缺项
- `允许发布`: 无 high-risk 缺项，且 medium-risk 缺项低于阈值

## Output Shape

Report should contain:

1. input summary
2. final decision
3. normalized decision code: `allow`, `revise`, or `block`
4. risk level
5. blocker list
6. missing items with repair advice
7. paste-ready issue comment

## Review Guidance

When a failure is found, advice should be repairable:

- bad: "release record is weak"
- good: "add at least one monitoring row with owner, threshold, observation window, and dashboard link in section 8"

## Known Limits

- script judges template completeness, not whether evidence itself is true
- table parsing is heuristic
- placeholder-like team conventions may reduce accuracy
- final release / rollback authority remains with DevOps / CTO
