#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SUBSECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_VALUES = {"", "-", "—", "/", "待补充", "todo", "tbd", "n/a"}
CASE_ID_RE = re.compile(r"^TC-\d+$")


@dataclass
class Finding:
    severity: str
    code: str
    title: str
    detail: str
    advice: str


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find_docs_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if parent.name == "docs":
            return parent
    return None


def derive_output_path(testcase_path: Path) -> Path:
    docs_root = find_docs_root(testcase_path)
    if docs_root is None:
        raise ValueError("`--output auto` requires the test case document to live under a `docs/` directory.")
    return docs_root / "review" / "test-case" / f"{testcase_path.stem}.test-case.generated.md"


def split_sections(markdown: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(markdown))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        sections[match.group(1).strip()] = markdown[start:end].strip()
    return sections


def split_subsections(section_body: str) -> dict[str, str]:
    matches = list(SUBSECTION_RE.finditer(section_body))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(section_body)
        sections[match.group(1).strip()] = section_body[start:end].strip()
    return sections


def is_placeholder(value: str) -> bool:
    clean = normalize_text(value).strip("`").lower()
    return clean in PLACEHOLDER_VALUES


def extract_bullet_value(section_body: str, label: str) -> str:
    pattern = re.compile(rf"^[ \t]*-[ \t]*{re.escape(label)}[ \t]*[:：][ \t]*(.*)$", re.MULTILINE)
    match = pattern.search(section_body)
    return match.group(1).strip() if match else ""


def extract_list_items(section_body: str) -> list[str]:
    return [
        normalize_text(line.split(" ", 1)[1])
        for line in section_body.splitlines()
        if re.match(r"^\s*-\s+.+$", line)
    ]


def extract_table_rows(section_body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section_body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell) <= {"-"} for cell in cells):
            continue
        rows.append(cells)
    if len(rows) <= 1:
        return []
    return rows[1:]


def make_finding(severity: str, code: str, title: str, detail: str, advice: str) -> Finding:
    return Finding(severity=severity, code=code, title=title, detail=detail, advice=advice)


def analyze_test_cases(markdown: str) -> dict:
    findings: list[Finding] = []
    passes: list[str] = []
    sections = split_sections(markdown)

    basic = sections.get("1. 基本信息", "")
    basic_fields = ["功能名称", "功能标识", "测试 owner", "关联 issue", "状态", "最后更新时间"]
    missing_basic = [field for field in basic_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_basic:
        findings.append(make_finding("medium", "basic.incomplete", "基本信息不完整", f"缺少字段：{', '.join(missing_basic)}。", "补齐功能名称、feature slug、测试 owner、状态和更新时间。"))
    else:
        passes.append("基本信息完整")

    related_fields = ["PRD", "UI 设计", "架构与技术设计", "OpenAPI"]
    missing_related = [field for field in related_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_related:
        findings.append(make_finding("high", "linkage.missing", "关联文档路径缺失", f"缺少字段：{', '.join(missing_related)}。", "补齐 PRD、UI、技术文档和 OpenAPI 路径。"))
    else:
        passes.append("关联路径完整")

    scope = sections.get("2. 测试范围", "")
    scope_parts = split_subsections(scope)
    in_scope = extract_list_items(scope_parts.get("范围内", ""))
    out_scope = extract_list_items(scope_parts.get("范围外", ""))
    if not in_scope or not out_scope:
        findings.append(make_finding("medium", "scope.weak", "测试范围边界不清晰", "范围内或范围外缺少有效条目。", "同时补范围内和范围外，避免测试范围漂移。"))
    else:
        passes.append("测试范围边界明确")

    focus = sections.get("3. 测试重点", "")
    focus_fields = ["主流程", "异常流程", "权限", "兼容性", "回归范围"]
    missing_focus = [field for field in focus_fields if is_placeholder(extract_bullet_value(focus, field))]
    if len(missing_focus) >= 3:
        findings.append(make_finding("medium", "focus.incomplete", "测试重点不完整", f"缺少字段：{', '.join(missing_focus)}。", "至少补主流程、异常流程和回归范围，其他按项目填写。"))
    else:
        passes.append("测试重点已登记")

    env = sections.get("4. 测试环境与数据", "")
    env_fields = ["环境", "账号", "测试数据准备", "Mock / 开关说明"]
    missing_env = [field for field in env_fields if is_placeholder(extract_bullet_value(env, field))]
    if missing_env:
        findings.append(make_finding("high", "env.missing", "测试环境或数据准备缺失", f"缺少字段：{', '.join(missing_env)}。", "补环境、账号、测试数据和 mock/开关说明，避免执行前临时补口头信息。"))
    else:
        passes.append("测试环境与数据准备完整")

    case_rows = extract_table_rows(sections.get("5. 测试用例", ""))
    valid_case_rows = [row for row in case_rows if len(row) >= 6 and any(not is_placeholder(cell) for cell in row)]
    if not valid_case_rows:
        findings.append(make_finding("high", "cases.missing", "缺少测试用例表", "没有结构化测试用例，无法执行或复核。", "至少补 1 行测试用例，包含前置条件、步骤、预期结果和优先级。"))
    else:
        invalid_case_ids = [row[0] for row in valid_case_rows if len(row) >= 1 and not CASE_ID_RE.match(row[0])]
        weak_rows = [row[0] for row in valid_case_rows if len(row) < 6 or any(is_placeholder(cell) for cell in row[:6])]
        if invalid_case_ids:
            findings.append(make_finding("medium", "cases.id_invalid", "测试用例编号不符合规范", f"不合规用例 ID：{', '.join(invalid_case_ids)}。", "使用 `TC-001` 这类稳定编号。"))
        if weak_rows:
            findings.append(make_finding("high", "cases.row_incomplete", "测试用例行不完整", f"存在字段不完整的用例：{', '.join(weak_rows)}。", "补齐场景、前置条件、步骤、预期结果和优先级。"))
        else:
            passes.append(f"测试用例存在 {len(valid_case_rows)} 行")

    regression = sections.get("6. 回归与 smoke", "")
    regression_fields = ["回归清单", "smoke 清单", "是否需要自动化"]
    missing_regression = [field for field in regression_fields if is_placeholder(extract_bullet_value(regression, field))]
    if missing_regression:
        findings.append(make_finding("medium", "regression.incomplete", "回归或 smoke 说明不完整", f"缺少字段：{', '.join(missing_regression)}。", "补回归清单、smoke 清单和自动化结论。"))
    else:
        passes.append("回归与 smoke 说明完整")

    risk_rows = extract_table_rows(sections.get("7. 风险与阻塞", ""))
    valid_risk_rows = [row for row in risk_rows if any(not is_placeholder(cell) for cell in row)]
    if not valid_risk_rows:
        findings.append(make_finding("medium", "risk.empty", "风险与阻塞未登记", "测试阶段的风险或阻塞没有结构化记录。", "至少补 1 行风险/阻塞，或显式写无。"))
    else:
        missing_owner = [row[0] for row in valid_risk_rows if len(row) < 2 or is_placeholder(row[1])]
        if missing_owner:
            findings.append(make_finding("high", "risk.owner_missing", "风险或阻塞缺少 owner", f"缺少 owner 的条目：{', '.join(missing_owner)}。", "给每条风险或阻塞指定 owner。"))
        else:
            passes.append("风险与阻塞 owner 明确")

    high_count = sum(1 for finding in findings if finding.severity == "high")
    medium_count = sum(1 for finding in findings if finding.severity == "medium")
    if high_count >= 2 or any(finding.code in {"linkage.missing", "env.missing", "cases.missing", "cases.row_incomplete", "risk.owner_missing"} for finding in findings):
        decision = "BLOCK"
        risk = "high"
    elif high_count == 1 or medium_count >= 3:
        decision = "REVISE_BEFORE_REVIEW"
        risk = "medium" if high_count == 0 else "high"
    else:
        decision = "ALLOW_TO_REVIEW"
        risk = "low" if medium_count == 0 else "medium"

    return {"decision": decision, "normalized_decision": {"ALLOW_TO_REVIEW": "allow", "REVISE_BEFORE_REVIEW": "revise", "BLOCK": "block"}[decision], "risk": risk, "passes": passes, "findings": [finding.__dict__ for finding in findings]}


def render_markdown(report: dict, testcase_path: str, issue: str | None) -> str:
    lines = [
        "# Test Case Review Report",
        "",
        f"- Test Cases: `{testcase_path}`",
        f"- Issue: `{issue or 'N/A'}`",
        f"- Decision: `{report['decision']}`",
        f"- Decision Code: `{report['normalized_decision']}`",
        f"- Risk: `{report['risk']}`",
        "",
        "## Checks",
        "",
    ]
    for item in report["passes"]:
        lines.append(f"- `[PASS]` {item}")
    for finding in report["findings"]:
        lines.append(f"- `[FAIL/{finding['severity'].upper()}]` {finding['title']}: {finding['detail']}")
    lines.extend(["", "## Findings", ""])
    if report["findings"]:
        for finding in report["findings"]:
            lines.extend([f"### {finding['title']} ({finding['severity']})", "", f"- Detail: {finding['detail']}", f"- Advice: {finding['advice']}", ""])
    else:
        lines.extend(["No blocking findings.", ""])
    lines.extend(["## Paste-Ready Comment", "", "状态：`test-case-checker` 已完成。", "", f"- 结论：`{report['decision']}`", f"- 统一决策码：`{report['normalized_decision']}`", f"- 风险：`{report['risk']}`"])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- {finding['severity']}：{finding['title']}。{finding['advice']}")
    else:
        lines.append("- 结构化检查通过，当前未发现需要阻断测试设计的缺项。")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run test case checks for template-based Markdown docs.")
    parser.add_argument("--testcase", required=True, help="Path to test case Markdown file")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    args = parser.parse_args()

    testcase_path = Path(args.testcase).resolve()
    markdown = read_text(testcase_path)
    report = analyze_test_cases(markdown)

    if args.format == "json":
        rendered = json.dumps({"testcase": str(testcase_path), "issue": args.issue, **report}, ensure_ascii=False, indent=2)
    else:
        rendered = render_markdown(report, str(testcase_path), args.issue)

    if args.output:
        output_path = derive_output_path(testcase_path) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
