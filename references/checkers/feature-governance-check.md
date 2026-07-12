# Feature Governance Check

## Purpose

`feature-governance-check` is the orchestration entrypoint that runs the feature-level governance checkers in sequence and summarizes the result.

It currently runs:

- `prd-qa-checker`
- `ui-design-checker`
- `test-case-checker`
- `architecture-design-checker`
- `artifact-consistency-checker`

## Input Contract

Recommended inputs:

- workspace root containing `docs/`
- feature slug
- optional issue identifier
- lifecycle stage: `intake`, `design`, `development`, `qa`, `release`, or `closure`

Recommended durable output path:

- `docs/review/feature-governance/{feature-slug}.feature-governance.generated.md`

## Output Shape

The summary should contain:

1. workspace and feature summary
2. final rolled-up decision
3. normalized decision code
4. highest risk level
5. per-module results
6. condensed findings summary
7. paste-ready issue comment

## Decision Aggregation

- final decision uses the strictest normalized decision across modules: `block > revise > allow`
- final risk uses the highest risk level across modules: `high > medium > low`
- only checkers whose inputs are required by the selected lifecycle stage are run

## Known Limits

- orchestration depends on the underlying checker scripts succeeding
- it does not yet run release readiness automatically because release records are event-scoped, not feature-scoped
