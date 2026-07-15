---
name: project-manager
description: Govern the complete project lifecycle from intake through design, development, QA, release, and closure using repository-owned artifacts, stage-aware gates, risks, and handoffs. Use when Codex needs to bootstrap feature or release records, review a PRD/UI design/technical design/test case/release record, audit cross-artifact consistency, run a lifecycle-stage gate, define role handoffs, or report milestone and artifact-readiness risks. Use project-structure-governance instead for document paths, naming, language, and repository archival rules.
---

# Project Manager

Use this skill as the complete project-lifecycle governance entrypoint. Judge artifact readiness and traceability; do not replace product, engineering, QA, or release owners' final decisions.

## Select The Lifecycle Stage

Use one explicit stage for every consolidated gate:

| Stage | Required outcome |
| --- | --- |
| `intake` | PRD is ready for downstream design |
| `design` | PRD and local UI handoff are ready |
| `development` | Technical contract, schema, owners, and test design are ready for implementation |
| `qa` | Development inputs remain consistent and test execution can proceed |
| `release` | Test evidence is present; run the event-scoped release gate separately |
| `closure` | Release is complete and retrospective evidence is archived |

## Route The Request

Inspect the supplied artifact path and requested outcome, then select the narrowest module:

| Request or artifact | Module | Read before use |
| --- | --- | --- |
| Initialize or audit project document paths and language | `$project-structure-governance` | Use that skill's canonical layout |
| Create a new feature documentation skeleton | `feature-doc-bootstrap` | [New Demand Checklist](references/standards/new-demand-init-checklist.md) |
| Create an event-scoped release record | `release-record-bootstrap` | [Release Template](references/templates/release-record-template.md) |
| Review `docs/product/<feature>/` | `prd-qa-checker` | [PRD QA Rules](references/checkers/prd-qa-checker.md) |
| Review `docs/design/<feature>/` and local design assets | `ui-design-checker` | [UI Design Rules](references/checkers/ui-design-checker.md) |
| Review `docs/development/<feature>/` | `architecture-design-checker` | [Architecture Rules](references/checkers/architecture-design-checker.md) |
| Validate `docs/development/<feature>/openapi/001-openapi.yaml` | `api-contract-checker` | [API Contract Rules](references/checkers/api-contract-checker.md) |
| Review `docs/testing/<feature>/test-cases/` | `test-case-checker` | [Test Case Rules](references/checkers/test-case-checker.md) |
| Review `docs/testing/<feature>/test-report/` | `test-report-checker` | [Test Report Rules](references/checkers/test-report-checker.md) |
| Review `docs/retrospective/<feature>/` | `retrospective-checker` | [Retrospective Rules](references/checkers/retrospective-checker.md) |
| Review milestones and risks | `project-status-checker` | [Project Status Rules](references/checkers/project-status-checker.md) |
| Audit one feature across all artifacts | `artifact-consistency-checker` | [Consistency Rules](references/checkers/artifact-consistency-checker.md) |
| Run the complete feature gate | `feature-governance-check` | [Governance Rules](references/checkers/feature-governance-check.md) |
| Review `docs/release/<release-event>/` | `release-readiness-checker` | [Release Rules](references/checkers/release-readiness-checker.md) |
| Define lifecycle workflow, roles, or handoffs | `project-development-standard` | [Development Standard](references/standards/project-development-standard.md) |

For a generic project-management check, inspect available documents first. Do not guess the module from the request wording alone. For API contract or design-to-implementation diff requests, apply the manual development standard; dedicated automated modules do not exist yet.

## Delegate Document Governance

Use `$project-structure-governance` before creating or auditing lifecycle artifacts. Treat its `references/project-layout.json` as the only authoritative path definition and its checker result as the document-storage gate. Do not redefine the complete directory layout in this skill.
Apply its [total-part document bundle standard](../project-structure-governance/references/document-bundle-standard.md): start every bundle with `001-overview.md`, keep one topic per numbered file, and use continuous three-digit numbering.

Before creating a feature artifact, search its canonical path returned by the structure-governance skill. Update an existing feature bundle and append numbered chapters or change records for enhancements or fixes instead of creating a parallel bundle. Continue to treat shared project state as non-overwritable during feature initialization.

## Run Modules

Run commands from this skill's repository root. Replace paths and identifiers with the target workspace values.

```bash
python3 scripts/feature_doc_bootstrap.py --workspace /path/to/repo --feature payment-confirmation --issue WAR-342
python3 scripts/release_record_bootstrap.py --workspace /path/to/repo --date 2026-07-12 --issue WAR-346 --slug payment-release
python3 scripts/prd_qa_checker.py --prd docs/product/payment-confirmation/ --issue WAR-342 --output auto
python3 scripts/ui_design_checker.py --ui docs/design/payment-confirmation/ --issue WAR-342 --output auto
python3 scripts/architecture_design_checker.py --design docs/development/payment-confirmation/ --issue WAR-342 --output auto
python3 scripts/api_contract_checker.py --input docs/development/payment-confirmation/openapi/001-openapi.yaml --baseline previous-openapi.yaml --fail-on block
python3 scripts/test_case_checker.py --testcase docs/testing/payment-confirmation/test-cases/ --issue WAR-342 --output auto
python3 scripts/artifact_consistency_checker.py --workspace /path/to/repo --feature payment-confirmation --stage development --issue WAR-342 --output auto
python3 scripts/feature_governance_check.py --workspace /path/to/repo --feature payment-confirmation --stage development --issue WAR-342 --output auto
python3 scripts/release_readiness_checker.py --release docs/release/2026-07-12-WAR-346-payment-release/ --issue WAR-346 --output auto
python3 scripts/test_report_checker.py --input docs/testing/payment-confirmation/test-report/
python3 scripts/retrospective_checker.py --input docs/retrospective/payment-confirmation/
python3 scripts/project_status_checker.py --input docs/project/project-status.yaml
```

Use `--format json` when another tool consumes a checker result. For CI feature gates, pass `--fail-on revise` or `--fail-on block` to `feature-governance-check`; it returns exit code 1 when the final decision reaches the selected threshold.
The standalone lifecycle checkers support the same `--fail-on` thresholds. Use `api-contract-checker --baseline` when a previous contract is available to detect removed operations.

## Apply The Output Contract

Return:

1. module-specific decision
2. normalized decision: `allow`, `revise`, or `block`
3. risk: `low`, `medium`, or `high`
4. passed checks
5. missing or weak items with concrete repair actions
6. a paste-ready issue comment when requested

Aggregate multiple modules using the strictest decision and highest risk. Save durable generated reports under `docs/review/...` and cite that path in issue comments.

Do not claim business correctness from structural checks. If an input diverges heavily from its template, state that coverage is partial and lower confidence. Do not invent missing requirements. Final release approval remains with the accountable release owner even when the checker returns `allow`.
