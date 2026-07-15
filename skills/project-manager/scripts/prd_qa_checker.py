#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from .document_bundle import document_slug, read_document
except ImportError:  # Support direct execution from the skill directory.
    from document_bundle import document_slug, read_document


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SUBSECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_VALUES = {"", "-", "—", "/", "待补充", "todo", "tbd", "n/a"}


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
    return read_document(path)


def find_docs_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if parent.name == "docs":
            return parent
    return None


def derive_output_path(prd_path: Path) -> Path:
    docs_root = find_docs_root(prd_path)
    if docs_root is None:
        raise ValueError("`--output auto` requires the PRD to live under a `docs/` directory.")
    return docs_root / "review" / "prd-qa" / f"{document_slug(prd_path)}.prd-qa.generated.md"


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


def extract_table_rows(section_body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section_body.splitlines():
        striped = line.strip()
        if not striped.startswith("|"):
            continue
        cells = [cell.strip() for cell in striped.strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell) <= {"-"} for cell in cells):
            continue
        rows.append(cells)
    if len(rows) <= 1:
        return []
    return rows[1:]


def count_numbered_steps(section_body: str) -> int:
    return len(re.findall(r"^\s*\d+\.\s+.+$", section_body, re.MULTILINE))


def extract_list_items(section_body: str) -> list[str]:
    return [
        normalize_text(line.split(" ", 1)[1])
        for line in section_body.splitlines()
        if re.match(r"^\s*-\s+.+$", line)
    ]


def make_finding(severity: str, code: str, title: str, detail: str, advice: str) -> Finding:
    return Finding(severity=severity, code=code, title=title, detail=detail, advice=advice)


def analyze_prd(markdown: str) -> dict:
    findings: list[Finding] = []
    passes: list[str] = []
    sections = split_sections(markdown)

    basic = sections.get("1. 基本信息", "")
    meta_fields = ["需求名称", "关联 issue", "目标版本 / 里程碑", "状态", "最后更新时间"]
    missing_meta = [field for field in meta_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_meta:
        findings.append(
            make_finding(
                "low",
                "meta.missing",
                "基本信息不完整",
                f"缺少字段：{', '.join(missing_meta)}。",
                "补齐基本信息，保证评审对象、版本和更新时间可追踪。",
            )
        )
    else:
        passes.append("基本信息完整")

    background = sections.get("2. 背景与目标", "")
    if is_placeholder(extract_bullet_value(background, "业务背景")):
        findings.append(
            make_finding(
                "medium",
                "background.missing",
                "缺少业务背景",
                "无法判断需求为什么存在。",
                "在第 2 节补一句可验证的业务背景，说明问题来源。",
            )
        )
    if is_placeholder(extract_bullet_value(background, "成功指标")):
        findings.append(
            make_finding(
                "medium",
                "metric.missing",
                "缺少成功指标",
                "下游无法判断完成后是否有效。",
                "补充至少 1 个可测量指标，如转化、时延、工单量或留存变化。",
            )
        )
    if not any(f.code in {"background.missing", "metric.missing"} for f in findings):
        passes.append("背景、目标、成功指标存在")

    users = sections.get("3. 用户与场景", "")
    user_rows = extract_table_rows(users)
    valid_user_rows = [row for row in user_rows if any(not is_placeholder(cell) for cell in row[:3])]
    if not valid_user_rows:
        findings.append(
            make_finding(
                "high",
                "user_scenario.missing",
                "缺少用户与场景",
                "下游无法确认谁在什么场景下使用功能。",
                "在第 3 节至少补 1 行用户、场景、目标，避免实现时猜测。",
            )
        )
    else:
        passes.append("用户与场景存在有效行")

    scope = sections.get("4. 范围", "")
    scope_parts = split_subsections(scope)
    in_scope = extract_list_items(scope_parts.get("范围内", ""))
    out_scope = extract_list_items(scope_parts.get("范围外", ""))
    if not in_scope or not out_scope:
        findings.append(
            make_finding(
                "medium",
                "scope.weak",
                "范围边界不清晰",
                "范围内或范围外缺少有效条目。",
                "同时补范围内与范围外，帮助设计和开发控制边界。",
            )
        )
    else:
        passes.append("范围内 / 范围外边界明确")

    main_flow = sections.get("5. 主流程", "")
    step_count = count_numbered_steps(main_flow)
    if step_count == 0:
        findings.append(
            make_finding(
                "high",
                "flow.missing",
                "缺少主流程",
                "实现方无法按顺序理解用户路径。",
                "在第 5 节按顺序列出主流程，至少覆盖进入、处理、结果三个阶段。",
            )
        )
    elif step_count < 3:
        findings.append(
            make_finding(
                "medium",
                "flow.too_short",
                "主流程过短",
                f"当前仅 {step_count} 步，可能遗漏关键状态转换。",
                "把触发、处理中间态、结果态补全为至少 3 步。",
            )
        )
    else:
        passes.append(f"主流程存在 {step_count} 步")

    states = sections.get("6. 状态与异常", "")
    state_rows = extract_table_rows(states)
    valid_state_rows = [row for row in state_rows if len(row) >= 5 and any(not is_placeholder(cell) for cell in row)]
    if not valid_state_rows:
        findings.append(
            make_finding(
                "high",
                "state.missing",
                "缺少状态与异常覆盖",
                "无法确认异常态、恢复动作和验收口径。",
                "在第 6 节至少补常态、失败态、可恢复动作和验收口径。",
            )
        )
    else:
        passes.append(f"状态与异常存在 {len(valid_state_rows)} 行")

    constraints = sections.get("7. 非功能约束", "")
    nfr_fields = ["权限", "性能", "兼容性", "风控", "埋点", "数据保留"]
    missing_nfr = [field for field in nfr_fields if is_placeholder(extract_bullet_value(constraints, field))]
    if len(missing_nfr) >= 3:
        findings.append(
            make_finding(
                "medium",
                "nfr.missing",
                "非功能约束不足",
                f"缺少字段：{', '.join(missing_nfr)}。",
                "至少补齐权限、性能、兼容性，其他按项目需要填写。",
            )
        )
    else:
        passes.append("非功能约束已填写")

    acceptance = sections.get("8. 验收标准", "")
    acceptance_items = extract_list_items(acceptance)
    if not acceptance_items:
        findings.append(
            make_finding(
                "high",
                "acceptance.missing",
                "缺少验收标准",
                "测试和评审无法据此判断完成定义。",
                "补充可测试、可观察、可判定通过/失败的验收标准。",
            )
        )
    else:
        passes.append(f"验收标准存在 {len(acceptance_items)} 条")

    deps = sections.get("9. 依赖与风险", "")
    dep_rows = extract_table_rows(deps)
    valid_dep_rows = [row for row in dep_rows if any(not is_placeholder(cell) for cell in row)]
    missing_owner_rows = [row for row in valid_dep_rows if len(row) < 2 or is_placeholder(row[1])]
    if not valid_dep_rows:
        findings.append(
            make_finding(
                "high",
                "dependency.missing",
                "缺少依赖与风险登记",
                "风险和外部依赖没有 owner，后续容易悬空。",
                "至少补 1 行依赖或风险，并明确 owner、动作和状态。",
            )
        )
    elif missing_owner_rows:
        findings.append(
            make_finding(
                "high",
                "dependency.owner_missing",
                "依赖与风险缺少 owner",
                "存在依赖项但 owner 为空。",
                "给每条依赖/风险指定 owner，否则无法闭环。",
            )
        )
    else:
        passes.append("依赖与风险 owner 明确")

    change_log = sections.get("10. 变更记录", "")
    if extract_table_rows(change_log):
        passes.append("变更记录已填写")
    else:
        findings.append(
            make_finding(
                "low",
                "changelog.empty",
                "变更记录为空",
                "PRD 可追溯性较弱。",
                "至少记录当前版本的起始变更，便于后续评审追踪。",
            )
        )

    high_count = sum(1 for finding in findings if finding.severity == "high")
    medium_count = sum(1 for finding in findings if finding.severity == "medium")
    if any(f.code == "acceptance.missing" for f in findings) or high_count >= 2:
        decision = "BLOCK"
        risk = "high"
    elif high_count == 1 or medium_count >= 3:
        decision = "REVISE_BEFORE_REVIEW"
        risk = "medium" if high_count == 0 else "high"
    else:
        decision = "ALLOW_TO_REVIEW"
        risk = "low" if medium_count == 0 else "medium"

    return {
        "decision": decision,
        "normalized_decision": decision_to_gate_code(decision),
        "risk": risk,
        "passes": passes,
        "findings": [finding.__dict__ for finding in findings],
    }


def decision_to_gate_code(decision: str) -> str:
    mapping = {
        "ALLOW_TO_REVIEW": "allow",
        "REVISE_BEFORE_REVIEW": "revise",
        "BLOCK": "block",
    }
    return mapping[decision]


def render_markdown(report: dict, prd_path: str, issue: str | None) -> str:
    lines = [
        "# PRD QA Report",
        "",
        f"- PRD: `{prd_path}`",
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
            lines.append(f"### {finding['title']} ({finding['severity']})")
            lines.append("")
            lines.append(f"- Detail: {finding['detail']}")
            lines.append(f"- Advice: {finding['advice']}")
            lines.append("")
    else:
        lines.append("No blocking findings.")
        lines.append("")

    lines.extend(
        [
            "## Paste-Ready Comment",
            "",
            f"状态：`prd-qa-checker` 已完成。",
            "",
            f"- 结论：`{report['decision']}`",
            f"- 统一决策码：`{report['normalized_decision']}`",
            f"- 风险：`{report['risk']}`",
        ]
    )
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- {finding['severity']}：{finding['title']}。{finding['advice']}")
    else:
        lines.append("- 结构化检查通过，当前未发现需要阻断评审的缺项。")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PRD quality checks for template-based Markdown PRDs.")
    parser.add_argument("--prd", required=True, help="Path to a PRD document bundle or legacy Markdown file")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    args = parser.parse_args()

    prd_path = Path(args.prd).resolve()
    markdown = read_text(prd_path)
    report = analyze_prd(markdown)

    if args.format == "json":
        rendered = json.dumps(
            {
                "prd": str(prd_path),
                "issue": args.issue,
                **report,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        rendered = render_markdown(report, str(prd_path), args.issue)

    if args.output:
        output_path = derive_output_path(prd_path) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
