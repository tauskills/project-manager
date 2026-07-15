#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STAGES = ("intake", "design", "development", "qa", "release", "closure")

CHECKERS = [
    {
        "name": "project-status-checker",
        "from_stage": "intake",
        "script": "project_status_checker.py",
        "args": lambda docs, feature, issue, stage: ["--input", str(docs / "project/project-status.yaml")],
    },
    {
        "name": "prd-qa-checker",
        "from_stage": "intake",
        "script": "prd_qa_checker.py",
        "args": lambda docs, feature, issue, stage: ["--prd", str(docs / "product" / feature), "--issue", issue] if issue else ["--prd", str(docs / "product" / feature)],
    },
    {
        "name": "ui-design-checker",
        "from_stage": "design",
        "script": "ui_design_checker.py",
        "args": lambda docs, feature, issue, stage: ["--ui", str(docs / "design" / feature), "--issue", issue] if issue else ["--ui", str(docs / "design" / feature)],
    },
    {
        "name": "test-case-checker",
        "from_stage": "development",
        "script": "test_case_checker.py",
        "args": lambda docs, feature, issue, stage: ["--testcase", str(docs / "testing" / feature / "test-cases"), "--issue", issue] if issue else ["--testcase", str(docs / "testing" / feature / "test-cases")],
    },
    {
        "name": "architecture-design-checker",
        "from_stage": "development",
        "script": "architecture_design_checker.py",
        "args": lambda docs, feature, issue, stage: ["--design", str(docs / "development" / feature), "--issue", issue] if issue else ["--design", str(docs / "development" / feature)],
    },
    {
        "name": "api-contract-checker",
        "from_stage": "development",
        "script": "api_contract_checker.py",
        "args": lambda docs, feature, issue, stage: ["--input", str(docs / "development" / feature / "openapi/001-openapi.yaml")],
    },
    {
        "name": "test-report-checker",
        "from_stage": "release",
        "script": "test_report_checker.py",
        "args": lambda docs, feature, issue, stage: ["--input", str(docs / "testing" / feature / "test-report")],
    },
    {
        "name": "retrospective-checker",
        "from_stage": "closure",
        "script": "retrospective_checker.py",
        "args": lambda docs, feature, issue, stage: ["--input", str(docs / "retrospective" / feature)],
    },
    {
        "name": "artifact-consistency-checker",
        "from_stage": "intake",
        "script": "artifact_consistency_checker.py",
        "args": lambda docs, feature, issue, stage: ["--workspace", str(docs.parent), "--feature", feature, "--stage", stage, *(["--issue", issue] if issue else [])],
    },
]

DECISION_ORDER = {"allow": 0, "revise": 1, "block": 2}
STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}


def checkers_for_stage(stage: str) -> list[dict]:
    return [checker for checker in CHECKERS if STAGE_ORDER[stage] >= STAGE_ORDER[checker["from_stage"]]]


def should_fail(decision: str, fail_on: str | None) -> bool:
    return fail_on is not None and DECISION_ORDER[decision] >= DECISION_ORDER[fail_on]


def run_checker(script_name: str, args: list[str]) -> dict:
    command = [sys.executable, str(SCRIPT_DIR / script_name), *args, "--format", "json"]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{script_name} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return json.loads(completed.stdout)


def combine_decisions(results: list[dict]) -> tuple[str, str]:
    normalized = max((item["normalized_decision"] for item in results), key=lambda value: DECISION_ORDER[value])
    decision_map = {"allow": "ALLOW_TO_REVIEW", "revise": "REVISE_BEFORE_REVIEW", "block": "BLOCK"}
    return decision_map[normalized], normalized


def combine_risk(results: list[dict]) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return max((item["risk"] for item in results), key=lambda value: order[value])


def render_markdown(workspace: Path, feature: str, issue: str | None, stage: str, results: list[dict]) -> str:
    final_decision, normalized = combine_decisions(results)
    risk = combine_risk(results)
    lines = [
        "# Feature Governance Report",
        "",
        f"- Workspace: `{workspace}`",
        f"- Feature: `{feature}`",
        f"- Issue: `{issue or 'N/A'}`",
        f"- Stage: `{stage}`",
        f"- Decision: `{final_decision}`",
        f"- Decision Code: `{normalized}`",
        f"- Risk: `{risk}`",
        "",
        "## Module Results",
        "",
    ]
    for result in results:
        name = result["module"]
        lines.append(f"- `{name}`: `{result['decision']}` / `{result['normalized_decision']}` / risk `{result['risk']}`")

    lines.extend(["", "## Findings Summary", ""])
    any_findings = False
    for result in results:
        findings = result.get("findings", [])
        if not findings:
            continue
        any_findings = True
        lines.append(f"### {result['module']}")
        lines.append("")
        for finding in findings:
            lines.append(f"- `{finding['severity']}` {finding['title']}：{finding['detail']}")
        lines.append("")
    if not any_findings:
        lines.extend(["No blocking findings.", ""])

    lines.extend(["## Paste-Ready Comment", "", "状态：`feature-governance-check` 已完成。", "", f"- 结论：`{final_decision}`", f"- 统一决策码：`{normalized}`", f"- 风险：`{risk}`"])
    for result in results:
        lines.append(f"- {result['module']}：`{result['normalized_decision']}`。")
    return "\n".join(lines).strip() + "\n"


def derive_output_path(workspace: Path, feature: str) -> Path:
    return workspace / "docs" / "review" / "feature-governance" / f"{feature}.feature-governance.generated.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all feature governance checkers and summarize the results.")
    parser.add_argument("--workspace", default=".", help="Business repo root where docs/ live")
    parser.add_argument("--feature", required=True, help="Stable feature slug, for example payment-confirmation")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--stage", choices=STAGES, default="development", help="Run only the checkers required through this lifecycle stage")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    parser.add_argument("--fail-on", choices=["revise", "block"], help="Return exit code 1 when the final decision reaches this threshold")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    docs = workspace / "docs"
    results: list[dict] = []
    for checker in checkers_for_stage(args.stage):
        payload = run_checker(checker["script"], checker["args"](docs, args.feature, args.issue, args.stage))
        payload["module"] = checker["name"]
        results.append(payload)

    final_decision, normalized = combine_decisions(results)
    risk = combine_risk(results)
    report = {
        "workspace": str(workspace),
        "feature": args.feature,
        "issue": args.issue,
        "stage": args.stage,
        "decision": final_decision,
        "normalized_decision": normalized,
        "risk": risk,
        "modules": results,
    }

    if args.format == "json":
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        rendered = render_markdown(workspace, args.feature, args.issue, args.stage, results)

    if args.output:
        output_path = derive_output_path(workspace, args.feature) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if should_fail(normalized, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
