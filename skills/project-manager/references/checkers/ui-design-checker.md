# UI Design Checker

## Purpose

`ui-design-checker` checks whether a feature's UI handoff document and local design assets are ready to enter frontend implementation or UI review.

It answers:

- Is the UI handoff document structurally complete?
- Are local design source files, screenshots, and exported assets actually present?
- Do screenshots and assets follow the repository naming conventions?

It does not answer:

- Whether the visual design is aesthetically optimal
- Whether the product direction is correct
- Whether the implementation cost is acceptable

## Input Contract

Recommended inputs:

- UI design Markdown path, canonical location `docs/design/{feature-slug}.md`
- optional issue identifier

Recommended durable output path:

- `docs/review/ui-design/{ui-file-stem}.ui-design.generated.md`

Expected local assets:

- `docs/design/{feature-slug}.fig`
- `docs/design/{feature-slug}/screens/`
- `docs/design/{feature-slug}/assets/`
- `docs/design/{feature-slug}/exports/`

## Rule Set

### High-risk checks

- missing local `.fig` design source
- missing screenshot directory or empty screenshots
- missing screenshot index in the Markdown handoff doc
- missing design asset paths
- missing page/state coverage

### Medium-risk checks

- missing design goals
- weak key flow
- incomplete state design
- missing component interaction notes
- missing acceptance focus
- invalid screenshot naming

### Low-risk checks

- missing optional asset directories
- invalid asset or export naming

## Decision Logic

- `BLOCK`: critical local assets missing, or 2 or more high-risk failures
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

## Naming Rules

- screenshots: `page-{page-name}-{state}.png`
- multi-platform screenshots: `page-{page-name}-{state}-{platform}.png`
- exports: `asset-{name}.{ext}`
- annotation images: `annot-{page-name}-{topic}.png`

## Known Limits

- script checks structural completeness and file presence, not visual quality
- it trusts screenshot filenames and does not validate image contents
- if teams use non-standard file extensions, naming checks may need updates
