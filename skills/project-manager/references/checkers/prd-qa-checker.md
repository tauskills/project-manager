# PRD QA Checker

## Purpose

`prd-qa-checker` checks whether a PRD is ready to enter design review or technical review.

It answers:

- Is required context present?
- Can downstream roles execute without guessing?
- Are acceptance and dependency owners explicit?

It does not answer:

- Whether strategy is correct
- Whether business priority is right
- Whether estimates are feasible

## Input Contract

Recommended inputs:

- PRD Markdown path, canonical location `docs/product/{feature-slug}/`
- optional issue identifier
- optional milestone / release identifier

Recommended durable output path:

- `docs/review/prd-qa/{prd-file-stem}.prd-qa.generated.md`

Best effort support:

- PRDs that roughly follow [PRD Template](../templates/prd-template.md)
- Markdown headings with Chinese section names

Lower-confidence cases:

- freeform docs without stable headings
- screenshots, slides, or docs embedded in tables only

## Rule Set

### High-risk checks

- missing user/role and scenario coverage
- missing main flow
- missing status/exception handling
- missing acceptance criteria
- missing dependency/risk owner

High-risk failures usually mean `BLOCK` or `REVISE_BEFORE_REVIEW`.

### Medium-risk checks

- missing business background
- missing success metrics
- missing non-goals
- missing non-functional constraints
- weak scope boundaries

### Low-risk checks

- incomplete basic metadata
- stale update date
- weak change log hygiene

## Documentation Policy

- PRD should be maintained per feature, not per small enhancement request
- if a request only updates an existing feature, update the existing PRD and append an update record
- avoid creating parallel PRDs for the same feature unless product scope truly splits into two different capabilities

## Decision Logic

- `BLOCK`: 2 or more high-risk failures, or acceptance criteria missing
- `REVISE_BEFORE_REVIEW`: 1 high-risk failure, or 3 or more medium-risk failures
- `ALLOW_TO_REVIEW`: no high-risk failures and medium-risk failures under threshold

## Output Shape

Report should contain:

1. input summary
2. final decision
3. normalized decision code: `allow`, `revise`, or `block`
4. risk level
5. pass/fail checklist
6. issue list with severity and repair advice
7. paste-ready issue comment

## Review Guidance

When a failure is found, advice should be repairable:

- bad: "needs more detail"
- good: "add at least one recoverable action for payment failure in section 6 state table"

## Known Limits

- script judges document structure, not domain truth
- table parsing is heuristic
- placeholder text may look non-empty if team uses unusual formatting
