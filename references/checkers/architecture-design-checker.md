# Architecture Design Checker

## Purpose

`architecture-design-checker` checks whether a new demand's architecture and technical design document is ready to enter development.

It answers:

- Is the implementation boundary fixed before development starts?
- Are technology choices, owners, and rollback plans explicit?
- Can frontend, backend, QA, and release roles execute without guessing?

It does not answer:

- Whether the architecture is globally optimal
- Whether the product direction is correct
- Whether engineering estimates are feasible

## Input Contract

Recommended inputs:

- architecture and technical design Markdown path, canonical location `docs/development/*.md`
- optional issue identifier

Recommended durable output path:

- `docs/review/architecture-design/{design-file-stem}.architecture-design.generated.md`

Best effort support:

- documents based on [Architecture Design Template](../templates/architecture-design-template.md)
- Markdown headings with Chinese section names

Lower-confidence cases:

- freeform docs without stable headings
- diagrams or screenshots without structured text

## Rule Set

### High-risk checks

- missing linked PRD / UI / OpenAPI / schema paths
- missing system boundary or call chain
- missing key technology choices
- missing implementation strategy
- missing role owners
- missing rollback plan

High-risk failures usually mean `BLOCK`.

### Medium-risk checks

- missing business background
- missing goals or non-goals
- incomplete impact scope
- missing exception handling
- incomplete reliability or security strategy
- missing OpenAPI / schema change summary
- missing testing or release requirements

### Low-risk checks

- incomplete conclusion
- empty pending confirmation items

## Decision Logic

- `BLOCK`: any critical high-risk failure, or 2 or more high-risk failures
- `REVISE_BEFORE_REVIEW`: 1 high-risk failure, or 3 or more medium-risk failures
- `ALLOW_TO_REVIEW`: no blocking high-risk failure and medium-risk failures under threshold

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

When a failure is found, advice should stay concrete:

- bad: "needs more technical detail"
- good: "state which service provides the API and which module owns idempotency"

## Known Limits

- script judges document completeness, not architecture quality
- it does not parse Mermaid or images as structured evidence
- placeholder text may look non-empty if the team uses unusual formatting
