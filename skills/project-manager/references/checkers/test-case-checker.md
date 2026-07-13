# Test Case Checker

## Purpose

`test-case-checker` checks whether a feature's test case document is ready to enter execution and QA review.

It answers:

- Is the test scope clear?
- Are environment, data, and mock requirements explicit?
- Are test cases structurally complete and reviewable?

It does not answer:

- Whether test priority is globally optimal
- Whether the product scope is correct
- Whether automation should definitely be implemented now

## Input Contract

Recommended inputs:

- test case Markdown path, canonical location `docs/testing/{feature-slug}-test-cases.md`
- optional issue identifier

Recommended durable output path:

- `docs/review/test-case/{testcase-file-stem}.test-case.generated.md`

## Rule Set

### High-risk checks

- missing linked PRD / UI / technical doc / OpenAPI paths
- missing test environment or test data setup
- missing test case table
- incomplete test case rows
- risk or blocker rows without owner

### Medium-risk checks

- weak scope boundaries
- incomplete test focus
- incomplete regression or smoke notes
- empty risk register
- invalid test case IDs

### Low-risk checks

- none currently beyond general document hygiene

## Decision Logic

- `BLOCK`: critical execution inputs missing, or 2 or more high-risk failures
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

## Known Limits

- script checks structural completeness, not domain truth
- it does not execute test cases or validate production parity
