# Artifact Consistency Checker

## Purpose

`artifact-consistency-checker` checks whether all feature-level artifacts for one `feature-slug` are present and cross-linked consistently.

It answers:

- Do PRD, UI, development, testing, and retrospective docs all exist?
- Do the documents reference each other using local repo paths?
- Are required local design assets and shared OpenAPI/schema files present?

It does not answer:

- Whether the content is semantically correct
- Whether design or implementation quality is high
- Whether release timing is appropriate

## Input Contract

Recommended inputs:

- workspace root containing `docs/`
- feature slug
- optional issue identifier
- lifecycle stage: `intake`, `design`, `development`, `qa`, `release`, or `closure`

Recommended durable output path:

- `docs/review/artifact-consistency/{feature-slug}.artifact-consistency.generated.md`

## Rule Set

Required artifacts are stage-aware. Later evidence such as test reports and retrospectives must not block an earlier development gate.

### High-risk checks

- missing canonical artifact files
- broken local doc paths
- missing UI screenshots

### Medium-risk checks

- missing cross-document references
- weak linkage between related docs

## Output Shape

Report should contain:

1. workspace and feature summary
2. final decision
3. normalized decision code
4. risk level
5. pass/fail checklist
6. issue list with severity and repair advice
7. paste-ready issue comment

## Known Limits

- script checks file presence and path linkage, not business correctness
- it does not parse image contents or OpenAPI semantics
