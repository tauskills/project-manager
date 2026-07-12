#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SUBSECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_VALUES = {
    "",
    "-",
    "—",
    "/",
    "待补充",
    "todo",
    "tbd",
    "n/a",
    "yes / no",
    "是 / 否",
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
    return path.read_text(encoding="utf-8")


def find_docs_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if parent.name == "docs":
            return parent
    return None


def derive_output_path(design_path: Path) -> Path:
    docs_root = find_docs_root(design_path)
    if docs_root is None:
        raise ValueError("`--output auto` requires the design document to live under a `docs/` directory.")
    return docs_root / "review" / "architecture-design" / f"{design_path.stem}.architecture-design.generated.md"


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


def count_numbered_steps(section_body: str) -> int:
    return len(re.findall(r"^[ \t]*\d+\.[ \t]+.+$", section_body, re.MULTILINE))


def any_non_placeholder(values: list[str]) -> bool:
    return any(not is_placeholder(value) for value in values)


def make_finding(severity: str, code: str, title: str, detail: str, advice: str) -> Finding:
    return Finding(severity=severity, code=code, title=title, detail=detail, advice=advice)


def analyze_design(markdown: str) -> dict:
    findings: list[Finding] = []
    passes: list[str] = []
    sections = split_sections(markdown)

    basic = sections.get("1. 基本信息", "")
    basic_fields = ["需求名称", "Issue Key", "文档作者", "技术 Owner", "创建日期", "状态"]
    missing_basic = [field for field in basic_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_basic:
        findings.append(
            make_finding(
                "medium",
                "basic.incomplete",
                "基本信息不完整",
                f"缺少字段：{', '.join(missing_basic)}。",
                "补齐需求标识、作者、技术 owner、日期和状态，保证文档可追踪。",
            )
        )
    else:
        passes.append("基本信息完整")

    linked_paths = [
        extract_bullet_value(basic, "PRD"),
        extract_bullet_value(basic, "UI 设计"),
        extract_bullet_value(basic, "OpenAPI"),
        extract_bullet_value(basic, "Schema"),
    ]
    if not any_non_placeholder(linked_paths):
        findings.append(
            make_finding(
                "high",
                "linkage.missing",
                "缺少关联文档路径",
                "PRD、UI、OpenAPI、Schema 路径未建立，跨角色无法按固定产物交接。",
                "至少补齐 PRD、UI、OpenAPI、Schema 的固定路径。",
            )
        )
    else:
        passes.append("关联文档路径已登记")

    background = sections.get("2. 背景与目标", "")
    background_subsections = split_subsections(background)
    goal_items = extract_list_items(background_subsections.get("2.2 本次目标", ""))
    nongoal_items = extract_list_items(background_subsections.get("2.3 本次不做", ""))
    if is_placeholder(extract_bullet_value(background_subsections.get("2.1 背景", ""), "当前业务问题是什么")):
        findings.append(
            make_finding(
                "medium",
                "background.missing",
                "缺少业务背景",
                "无法判断为什么需要当前技术方案。",
                "补一句可验证的业务背景，说明问题来源和影响范围。",
            )
        )
    if not goal_items or not nongoal_items:
        findings.append(
            make_finding(
                "medium",
                "scope.weak",
                "目标或非目标缺失",
                "本次要解决什么、明确不做什么没有同时写清楚。",
                "同时补“本次目标”和“本次不做”，控制实现边界。",
            )
        )
    if goal_items and nongoal_items:
        passes.append("目标和非目标边界明确")

    impact = sections.get("3. 范围与影响面", "")
    impact_fields = ["涉及端", "涉及服务或仓库", "涉及上下游系统"]
    missing_impact = [field for field in impact_fields if is_placeholder(extract_bullet_value(impact, field))]
    if missing_impact:
        findings.append(
            make_finding(
                "medium",
                "impact.missing",
                "范围与影响面不完整",
                f"缺少字段：{', '.join(missing_impact)}。",
                "补齐涉及端、服务/仓库、上下游系统，避免开发和测试遗漏依赖。",
            )
        )
    else:
        passes.append("范围与影响面已登记")

    boundaries = sections.get("4. 系统边界与调用关系", "")
    boundary_subsections = split_subsections(boundaries)
    module_values = [
        extract_bullet_value(boundary_subsections.get("4.1 模块边界", ""), "本次改动模块"),
        extract_bullet_value(boundary_subsections.get("4.1 模块边界", ""), "复用的现有能力"),
    ]
    call_steps = count_numbered_steps(boundary_subsections.get("4.2 调用链路", ""))
    exception_items = extract_list_items(boundary_subsections.get("4.3 异常链路", ""))
    if not any_non_placeholder(module_values) or call_steps < 2:
        findings.append(
            make_finding(
                "high",
                "boundary.weak",
                "系统边界或调用链路不清晰",
                f"当前调用链路仅识别到 {call_steps} 步，或模块边界仍未明确。",
                "补齐改动模块、复用能力和至少 2 步调用链路，明确服务之间如何协作。",
            )
        )
    else:
        passes.append(f"系统边界与调用链路存在 {call_steps} 步")
    if not exception_items:
        findings.append(
            make_finding(
                "medium",
                "exception.missing",
                "缺少异常链路",
                "失败场景和恢复动作未定义，联调和测试难以覆盖风险。",
                "补至少 1 个异常场景，说明触发条件和处理方式。",
            )
        )
    else:
        passes.append(f"异常链路存在 {len(exception_items)} 项")

    choices = sections.get("5. 技术选型", "")
    choice_fields = ["开发语言", "框架", "数据库"]
    missing_choices = [field for field in choice_fields if is_placeholder(extract_bullet_value(choices, field))]
    if missing_choices:
        findings.append(
            make_finding(
                "high",
                "tech_choice.missing",
                "技术选型不完整",
                f"缺少字段：{', '.join(missing_choices)}。",
                "至少明确语言、框架、数据库，避免实现阶段再临时决策。",
            )
        )
    else:
        passes.append("关键技术选型明确")

    strategy = sections.get("6. 实现策略", "")
    strategy_subsections = split_subsections(strategy)
    flow_values = [
        extract_bullet_value(strategy_subsections.get("6.1 核心流程", ""), "主流程步骤"),
        extract_bullet_value(strategy_subsections.get("6.1 核心流程", ""), "状态流转"),
    ]
    data_values = [
        extract_bullet_value(strategy_subsections.get("6.2 数据落点", ""), "写入哪些表"),
        extract_bullet_value(strategy_subsections.get("6.2 数据落点", ""), "读取哪些表"),
    ]
    service_values = [
        extract_bullet_value(strategy_subsections.get("6.3 接口实现归属", ""), "哪个服务提供接口"),
        extract_bullet_value(strategy_subsections.get("6.3 接口实现归属", ""), "哪个模块负责业务逻辑"),
    ]
    reliability_fields = ["事务策略", "幂等策略", "超时策略"]
    missing_reliability = [
        field for field in reliability_fields if is_placeholder(extract_bullet_value(strategy_subsections.get("6.4 一致性与可靠性", ""), field))
    ]
    security_fields = ["鉴权方式", "权限控制"]
    missing_security = [
        field for field in security_fields if is_placeholder(extract_bullet_value(strategy_subsections.get("6.5 权限与安全", ""), field))
    ]
    if not any_non_placeholder(flow_values + data_values + service_values):
        findings.append(
            make_finding(
                "high",
                "strategy.missing",
                "缺少实现策略",
                "核心流程、数据落点或接口归属为空，无法指导前后端实施。",
                "补齐核心流程、数据落点、接口提供服务和业务逻辑归属。",
            )
        )
    else:
        passes.append("实现策略已写明")
    if missing_reliability:
        findings.append(
            make_finding(
                "medium",
                "reliability.incomplete",
                "一致性与可靠性策略不完整",
                f"缺少字段：{', '.join(missing_reliability)}。",
                "补事务、幂等、超时等处理策略，避免异常时口径不一致。",
            )
        )
    else:
        passes.append("一致性与可靠性策略明确")
    if missing_security:
        findings.append(
            make_finding(
                "medium",
                "security.incomplete",
                "权限与安全策略不完整",
                f"缺少字段：{', '.join(missing_security)}。",
                "至少明确鉴权方式和权限控制边界。",
            )
        )
    else:
        passes.append("权限与安全策略明确")

    contract = sections.get("7. OpenAPI 与 Schema 变更摘要", "")
    contract_subsections = split_subsections(contract)
    api_values = [
        extract_bullet_value(contract_subsections.get("7.1 OpenAPI 变更摘要", ""), "新增接口"),
        extract_bullet_value(contract_subsections.get("7.1 OpenAPI 变更摘要", ""), "修改接口"),
        extract_bullet_value(contract_subsections.get("7.1 OpenAPI 变更摘要", ""), "删除接口"),
    ]
    schema_values = [
        extract_bullet_value(contract_subsections.get("7.2 Schema 变更摘要", ""), "新增表"),
        extract_bullet_value(contract_subsections.get("7.2 Schema 变更摘要", ""), "修改表"),
    ]
    if not any_non_placeholder(api_values):
        findings.append(
            make_finding(
                "medium",
                "openapi.summary_missing",
                "OpenAPI 变更摘要缺失",
                "接口变化没有在技术文档中做摘要，评审时需要来回跳转。",
                "补新增/修改/删除接口摘要，并确保正式定义写入 openapi.yaml。",
            )
        )
    else:
        passes.append("OpenAPI 变更摘要已登记")
    if not any_non_placeholder(schema_values):
        findings.append(
            make_finding(
                "medium",
                "schema.summary_missing",
                "Schema 变更摘要缺失",
                "数据结构变化没有在技术文档中做摘要。",
                "补表和索引变化摘要，并链接正式 SQL 文件。",
            )
        )
    else:
        passes.append("Schema 变更摘要已登记")

    owners = sections.get("8. 角色分工", "")
    owner_fields = ["架构/技术 Owner", "前端负责人", "后端负责人", "测试负责人", "发布负责人"]
    missing_owners = [field for field in owner_fields if is_placeholder(extract_bullet_value(owners, field))]
    if missing_owners:
        findings.append(
            make_finding(
                "high",
                "owner.missing",
                "角色分工不完整",
                f"缺少字段：{', '.join(missing_owners)}。",
                "补齐主要负责角色，避免跨团队交付悬空。",
            )
        )
    else:
        passes.append("角色分工明确")

    risks = sections.get("9. 风险与待确认事项", "")
    risk_subsections = split_subsections(risks)
    risk_values = [
        extract_bullet_value(risk_subsections.get("9.1 技术风险", ""), "风险"),
        extract_bullet_value(risk_subsections.get("9.1 技术风险", ""), "Owner"),
        extract_bullet_value(risk_subsections.get("9.2 依赖风险", ""), "风险"),
        extract_bullet_value(risk_subsections.get("9.2 依赖风险", ""), "Owner"),
    ]
    pending_values = [
        extract_bullet_value(risk_subsections.get("9.3 待确认事项", ""), "待确认项"),
        extract_bullet_value(risk_subsections.get("9.3 待确认事项", ""), "需要谁确认"),
    ]
    if not any_non_placeholder(risk_values):
        findings.append(
            make_finding(
                "high",
                "risk.missing",
                "缺少风险登记",
                "技术风险和依赖风险没有 owner，无法跟踪闭环。",
                "至少补 1 条风险并指定 owner、动作和截止时间。",
            )
        )
    else:
        passes.append("风险登记存在")
    if not any_non_placeholder(pending_values):
        findings.append(
            make_finding(
                "low",
                "pending.empty",
                "待确认事项为空",
                "如果当前确实没有待确认事项，可以显式写“无”。",
                "显式记录待确认事项，或写明“无”以避免评审误判为遗漏。",
            )
        )
    else:
        passes.append("待确认事项已登记")

    release = sections.get("10. 测试、发布与回滚", "")
    release_subsections = split_subsections(release)
    testing_values = [
        extract_bullet_value(release_subsections.get("10.1 测试要求", ""), "测试重点"),
        extract_bullet_value(release_subsections.get("10.1 测试要求", ""), "回归范围"),
    ]
    release_values = [
        extract_bullet_value(release_subsections.get("10.2 发布要求", ""), "发布前置条件"),
        extract_bullet_value(release_subsections.get("10.2 发布要求", ""), "监控指标"),
    ]
    rollback_values = [
        extract_bullet_value(release_subsections.get("10.3 回滚方案", ""), "代码回滚"),
        extract_bullet_value(release_subsections.get("10.3 回滚方案", ""), "数据回滚"),
    ]
    if not any_non_placeholder(testing_values):
        findings.append(
            make_finding(
                "medium",
                "testing.missing",
                "测试要求缺失",
                "测试重点和回归范围未写明，QA 难以据此设计用例。",
                "补测试重点、回归范围和是否需要 mock / 测试数据。",
            )
        )
    else:
        passes.append("测试要求已登记")
    if not any_non_placeholder(release_values):
        findings.append(
            make_finding(
                "medium",
                "release_plan.missing",
                "发布要求缺失",
                "发布前置条件和监控指标未写明。",
                "补发布前置条件、灰度要求和监控指标。",
            )
        )
    else:
        passes.append("发布要求已登记")
    if not any_non_placeholder(rollback_values):
        findings.append(
            make_finding(
                "high",
                "rollback.missing",
                "回滚方案缺失",
                "没有代码或数据回滚方案，发布风险无法评估。",
                "补代码回滚和数据回滚动作，至少说明回滚入口和限制条件。",
            )
        )
    else:
        passes.append("回滚方案已登记")

    conclusion = sections.get("11. 结论", "")
    if is_placeholder(extract_bullet_value(conclusion, "是否满足进入开发")):
        findings.append(
            make_finding(
                "low",
                "conclusion.empty",
                "结论未填写",
                "当前文档没有明确给出是否可进入开发的判断。",
                "补 `yes` / `no` 结论，并写明阻塞项和下一步动作。",
            )
        )
    else:
        passes.append("进入开发结论已填写")

    high_count = sum(1 for finding in findings if finding.severity == "high")
    medium_count = sum(1 for finding in findings if finding.severity == "medium")
    if high_count >= 2 or any(
        finding.code in {"linkage.missing", "boundary.weak", "tech_choice.missing", "strategy.missing", "owner.missing", "rollback.missing"}
        for finding in findings
    ):
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


def render_markdown(report: dict, design_path: str, issue: str | None) -> str:
    lines = [
        "# Architecture Design Review Report",
        "",
        f"- Design Doc: `{design_path}`",
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
            "状态：`architecture-design-checker` 已完成。",
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
        lines.append("- 结构化检查通过，当前未发现需要阻断开发的缺项。")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run architecture and technical design checks for template-based Markdown docs.")
    parser.add_argument("--design", required=True, help="Path to architecture and technical design Markdown file")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    args = parser.parse_args()

    design_path = Path(args.design).resolve()
    markdown = read_text(design_path)
    report = analyze_design(markdown)

    if args.format == "json":
        rendered = json.dumps(
            {
                "design": str(design_path),
                "issue": args.issue,
                **report,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        rendered = render_markdown(report, str(design_path), args.issue)

    if args.output:
        output_path = derive_output_path(design_path) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
