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
PLACEHOLDER_VALUES = {"", "-", "—", "/", "待补充", "todo", "tbd", "n/a", "无"}
PLACEHOLDER_PHRASES = {
    "新增 / 修改 / 删除 / 无变更",
    "是 / 否",
    "成功 / 回滚 / 失败",
    "待发布 / 发布中 / 观察中 / 已完成 / 已回滚",
    "通过 / 有条件通过 / 不通过 / 例外批准待补齐",
}


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


def derive_output_path(release_path: Path) -> Path:
    docs_root = find_docs_root(release_path)
    if docs_root is None:
        raise ValueError("`--output auto` requires the release record to live under a `docs/` directory.")
    return docs_root / "review" / "release-readiness" / f"{document_slug(release_path)}.release-readiness.generated.md"


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
    clean = normalize_text(value).strip("`")
    lower = clean.lower()
    return lower in PLACEHOLDER_VALUES or clean in PLACEHOLDER_PHRASES


def extract_bullet_value(section_body: str, label: str) -> str:
    pattern = re.compile(rf"^[ \t]*-[ \t]*{re.escape(label)}[ \t]*[:：][ \t]*(.*)$", re.MULTILINE)
    match = pattern.search(section_body)
    return match.group(1).strip() if match else ""


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


def count_numbered_steps(section_body: str) -> int:
    return len(re.findall(r"^[ \t]*\d+\.[ \t]+.+$", section_body, re.MULTILINE))


def extract_list_items(section_body: str) -> list[str]:
    return [
        normalize_text(line.split(" ", 1)[1])
        for line in section_body.splitlines()
        if re.match(r"^\s*-\s+.+$", line)
    ]


def has_non_placeholder_row(rows: list[list[str]]) -> bool:
    return any(any(not is_placeholder(cell) for cell in row) for row in rows)


def row_has_placeholder(rows: list[list[str]], index: int) -> bool:
    return any(len(row) <= index or is_placeholder(row[index]) for row in rows if any(not is_placeholder(cell) for cell in row))


def make_finding(severity: str, code: str, title: str, detail: str, advice: str) -> Finding:
    return Finding(severity=severity, code=code, title=title, detail=detail, advice=advice)


def analyze_release_record(markdown: str) -> dict:
    findings: list[Finding] = []
    passes: list[str] = []
    sections = split_sections(markdown)

    basic = sections.get("1. 基本信息", "")
    basic_fields = [
        "发布名称",
        "发布环境",
        "版本号",
        "构建号 / 镜像 tag / 包体标识",
        "发布时间窗口",
        "观察窗口",
        "值班 owner / 联系方式",
    ]
    missing_basic = [field for field in basic_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_basic:
        findings.append(
            make_finding(
                "medium",
                "basic.incomplete",
                "基本发布信息不完整",
                f"缺少字段：{', '.join(missing_basic)}。",
                "补齐版本、环境、发布时间窗口、观察窗口和值班信息，避免进入发布窗口后再口头补充。",
            )
        )
    else:
        passes.append("基本发布信息完整")

    gates = sections.get("3. 发布前门禁", "")
    gate_rows = extract_table_rows(gates)
    valid_gate_rows = [row for row in gate_rows if any(not is_placeholder(cell) for cell in row)]
    if not valid_gate_rows:
        findings.append(
            make_finding(
                "high",
                "gates.missing",
                "缺少发布前门禁结论",
                "QA / 产品 / UI / 技术 / 回滚门禁没有结构化记录。",
                "按模板补齐五类门禁结论、证据和备注；没有结论时不要进入放行讨论。",
            )
        )
    elif row_has_placeholder(valid_gate_rows, 2):
        findings.append(
            make_finding(
                "high",
                "gates.conclusion_missing",
                "门禁结论不完整",
                "至少一类门禁的“结论”列为空或仍是占位值。",
                "逐项补齐 QA、产品、UI、技术、回滚门禁结论，并给出对应证据。",
            )
        )
    else:
        passes.append("五类门禁均有结论")

    config = sections.get("4. 环境变量与配置差异", "")
    config_rows = extract_table_rows(config)
    if not has_non_placeholder_row(config_rows):
        findings.append(
            make_finding(
                "high",
                "config.missing",
                "缺少环境差异说明",
                "环境变量 / 配置差异表为空，无法确认是否存在配置风险。",
                "即使无变更也要显式登记一行“无变更”，并写明配置来源、owner 和验证结果。",
            )
        )
    else:
        passes.append("环境变量 / 配置差异已登记")

    dependency = sections.get("5. 变更依赖明细", "")
    dependency_parts = split_subsections(dependency)
    db_rows = extract_table_rows(dependency_parts.get("5.1 数据库 / 数据变更", ""))
    asset_rows = extract_table_rows(dependency_parts.get("5.2 静态资源 / 包体变更", ""))
    external_rows = extract_table_rows(dependency_parts.get("5.3 外部依赖变更", ""))
    if all(not has_non_placeholder_row(rows) for rows in [db_rows, asset_rows, external_rows]):
        findings.append(
            make_finding(
                "medium",
                "change_scope.missing",
                "变更依赖未登记",
                "数据库 / 静态资源 / 外部依赖三类变更都没有有效记录。",
                "至少显式声明每类是否变更；无变更也写“否”，避免默认假设。",
            )
        )
    else:
        passes.append("变更依赖已登记")

    release_steps = sections.get("6. 发布步骤", "")
    release_step_count = count_numbered_steps(release_steps)
    if release_step_count < 2:
        findings.append(
            make_finding(
                "medium",
                "release_steps.weak",
                "发布步骤过弱",
                f"当前仅识别到 {release_step_count} 个步骤，执行路径不够清晰。",
                "至少补齐发布前检查、执行动作、发布后验证三个阶段。",
            )
        )
    else:
        passes.append(f"发布步骤存在 {release_step_count} 步")

    rollback = sections.get("7. 回滚步骤", "")
    rollback_step_count = count_numbered_steps(rollback)
    trigger_items = extract_list_items(split_subsections(rollback).get("7.1 回滚触发条件", rollback))
    if rollback_step_count == 0:
        findings.append(
            make_finding(
                "high",
                "rollback.missing",
                "缺少回滚步骤",
                "没有可执行回滚步骤，发布失败时无法快速收敛影响。",
                "至少补齐回滚入口、回退动作、回滚后验证三步。",
            )
        )
    elif not trigger_items or all(is_placeholder(item) for item in trigger_items):
        findings.append(
            make_finding(
                "high",
                "rollback.trigger_missing",
                "缺少回滚触发条件",
                "有回滚步骤但没有说明何时触发回滚。",
                "补充明确触发阈值或场景，例如错误率、核心链路失败或 smoke 不通过。",
            )
        )
    else:
        passes.append("回滚步骤与触发条件存在")

    monitoring = sections.get("8. 监控与观察", "")
    monitoring_rows = extract_table_rows(monitoring)
    valid_monitoring_rows = [row for row in monitoring_rows if any(not is_placeholder(cell) for cell in row)]
    if not valid_monitoring_rows:
        findings.append(
            make_finding(
                "high",
                "monitoring.missing",
                "缺少监控与观察计划",
                "监控 owner、阈值、观察窗口或面板信息未登记。",
                "按模板补至少一行监控项，并写明 owner、阈值 / 观察点、观察窗口和面板或日志链接。",
            )
        )
    elif row_has_placeholder(valid_monitoring_rows, 1):
        findings.append(
            make_finding(
                "high",
                "monitoring.owner_missing",
                "监控 owner 缺失",
                "存在监控项，但 owner 列为空或仍是占位值。",
                "给每个监控项指定 owner，避免观察窗口内无人值守。",
            )
        )
    else:
        passes.append("监控 owner / 阈值 / 观察窗口明确")

    smoke = sections.get("9. smoke 检查", "")
    smoke_rows = extract_table_rows(smoke)
    if not has_non_placeholder_row(smoke_rows):
        findings.append(
            make_finding(
                "medium",
                "smoke.missing",
                "缺少 smoke 检查登记",
                "没有结构化记录 smoke 检查项、入口或结果。",
                "至少补一行 smoke 检查项，覆盖入口、owner、执行方式和结果。",
            )
        )
    else:
        passes.append("smoke 检查已登记")

    high_count = sum(1 for finding in findings if finding.severity == "high")
    medium_count = sum(1 for finding in findings if finding.severity == "medium")
    if high_count >= 2 or any(f.code in {"rollback.missing", "gates.missing", "gates.conclusion_missing"} for f in findings):
        decision = "不允许发布"
        risk = "high"
    elif high_count == 1 or medium_count >= 3:
        decision = "有条件允许发布"
        risk = "medium" if high_count == 0 else "high"
    else:
        decision = "允许发布"
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
        "允许发布": "allow",
        "有条件允许发布": "revise",
        "不允许发布": "block",
    }
    return mapping[decision]


def render_markdown(report: dict, release_path: str, issue: str | None) -> str:
    high_findings = [finding for finding in report["findings"] if finding["severity"] == "high"]
    medium_findings = [finding for finding in report["findings"] if finding["severity"] == "medium"]
    low_findings = [finding for finding in report["findings"] if finding["severity"] == "low"]

    lines = [
        "# Release Readiness Report",
        "",
        "## 1. 结论摘要",
        "",
        f"- 发布记录：`{release_path}`",
        f"- 关联 issue / 里程碑：`{issue or 'N/A'}`",
        f"- 检查结论：`{report['decision']}`",
        f"- 统一决策码：`{report['normalized_decision']}`",
        f"- 风险等级：`{report['risk']}`",
        "",
        "## 2. 阻断风险",
        "",
    ]
    if high_findings:
        for idx, finding in enumerate(high_findings, start=1):
            lines.append(f"{idx}. {finding['title']}：{finding['detail']} 建议：{finding['advice']}")
    else:
        lines.append("无")

    lines.extend(["", "## 3. 中风险", ""])
    if medium_findings:
        for idx, finding in enumerate(medium_findings, start=1):
            lines.append(f"{idx}. {finding['title']}：{finding['detail']} 建议：{finding['advice']}")
    else:
        lines.append("无")

    lines.extend(
        [
            "",
            "## 4. 缺项清单",
            "",
            "| 项目 | 当前状态 | 要求动作 |",
            "| --- | --- | --- |",
        ]
    )
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"| {finding['title']} | {finding['detail']} | {finding['advice']} |")
    else:
        lines.append("| 无 | 已通过 | 无 |")

    lines.extend(["", "## 5. 已通过检查", ""])
    if report["passes"]:
        for item in report["passes"]:
            lines.append(f"- `[PASS]` {item}")
    else:
        lines.append("- 无")
    if low_findings:
        for finding in low_findings:
            lines.append(f"- `[LOW]` {finding['title']}：{finding['detail']}")

    lines.extend(
        [
            "",
            "## 6. Paste-Ready Comment",
            "",
            "状态：`release-readiness-checker` 已完成。",
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
        lines.append("- 结构化发布检查通过，当前未发现阻断发布的缺项。")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run release readiness checks for template-based Markdown release records.")
    parser.add_argument("--release", required=True, help="Path to a release document bundle or legacy Markdown file")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    args = parser.parse_args()

    release_path = Path(args.release).resolve()
    markdown = read_text(release_path)
    report = analyze_release_record(markdown)

    if args.format == "json":
        rendered = json.dumps(
            {
                "release": str(release_path),
                "issue": args.issue,
                **report,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        rendered = render_markdown(report, str(release_path), args.issue)

    if args.output:
        output_path = derive_output_path(release_path) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
