#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_VALUES = {"", "-", "—", "/", "待补充", "todo", "tbd", "n/a"}
SCREENSHOT_NAME_RE = re.compile(r"^page-[a-z0-9-]+-[a-z0-9-]+(?:-[a-z0-9-]+)?\.(png|jpg|jpeg|webp)$")
ASSET_NAME_RE = re.compile(r"^asset-[a-z0-9-]+\.[a-z0-9]+$")
ANNOT_NAME_RE = re.compile(r"^annot-[a-z0-9-]+-[a-z0-9-]+\.(png|jpg|jpeg|webp)$")


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


def derive_output_path(ui_path: Path) -> Path:
    docs_root = find_docs_root(ui_path)
    if docs_root is None:
        raise ValueError("`--output auto` requires the UI design document to live under a `docs/` directory.")
    return docs_root / "review" / "ui-design" / f"{ui_path.stem}.ui-design.generated.md"


def split_sections(markdown: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(markdown))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        sections[match.group(1).strip()] = markdown[start:end].strip()
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


def count_numbered_steps(section_body: str) -> int:
    return len(re.findall(r"^[ \t]*\d+\.[ \t]+.+$", section_body, re.MULTILINE))


def list_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(item for item in path.iterdir() if item.is_file())


def make_finding(severity: str, code: str, title: str, detail: str, advice: str) -> Finding:
    return Finding(severity=severity, code=code, title=title, detail=detail, advice=advice)


def analyze_ui_design(markdown: str, ui_doc_path: Path) -> dict:
    findings: list[Finding] = []
    passes: list[str] = []
    sections = split_sections(markdown)

    basic = sections.get("1. 基本信息", "")
    basic_fields = ["功能名称", "功能标识", "UI owner", "关联 issue", "状态", "最后更新时间"]
    missing_basic = [field for field in basic_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_basic:
        findings.append(make_finding("medium", "basic.incomplete", "基本信息不完整", f"缺少字段：{', '.join(missing_basic)}。", "补齐功能名称、feature slug、UI owner、状态和更新时间。"))
    else:
        passes.append("基本信息完整")

    related_fields = ["PRD", "架构与技术设计", "测试用例", "本地设计源文件", "页面截图目录"]
    missing_related = [field for field in related_fields if is_placeholder(extract_bullet_value(basic, field))]
    if missing_related:
        findings.append(make_finding("high", "linkage.missing", "关联文档或设计资产路径缺失", f"缺少字段：{', '.join(missing_related)}。", "补齐 PRD、技术文档、测试用例、本地设计源文件和截图目录路径。"))
    else:
        passes.append("关联路径完整")

    goals = sections.get("2. 设计目标", "")
    goal_fields = ["本次解决的问题", "关键用户目标", "非目标"]
    missing_goals = [field for field in goal_fields if is_placeholder(extract_bullet_value(goals, field))]
    if missing_goals:
        findings.append(make_finding("medium", "goals.incomplete", "设计目标不完整", f"缺少字段：{', '.join(missing_goals)}。", "补齐问题、目标和非目标，避免设计范围漂移。"))
    else:
        passes.append("设计目标明确")

    scope_rows = extract_table_rows(sections.get("3. 页面与入口范围", ""))
    valid_scope_rows = [row for row in scope_rows if any(not is_placeholder(cell) for cell in row)]
    if not valid_scope_rows:
        findings.append(make_finding("high", "scope.missing", "缺少页面与入口范围", "前端和测试无法确认本次覆盖哪些页面和入口。", "至少补 1 行页面、入口和范围结论。"))
    else:
        passes.append("页面与入口范围已登记")

    flow_steps = count_numbered_steps(sections.get("4. 关键流程", ""))
    if flow_steps < 3:
        findings.append(make_finding("medium", "flow.weak", "关键流程过弱", f"当前仅识别到 {flow_steps} 步。", "补至少 3 步，覆盖进入、处理和结果。"))
    else:
        passes.append(f"关键流程存在 {flow_steps} 步")

    state_rows = extract_table_rows(sections.get("5. 状态设计", ""))
    valid_state_rows = [row for row in state_rows if len(row) >= 4 and any(not is_placeholder(cell) for cell in row)]
    if len(valid_state_rows) < 3:
        findings.append(make_finding("high", "states.missing", "状态设计覆盖不足", "默认态、异常态或关键状态没有结构化记录。", "至少补默认态、加载态、错误态等关键状态。"))
    else:
        passes.append(f"状态设计存在 {len(valid_state_rows)} 行")

    component_rows = extract_table_rows(sections.get("6. 组件与交互说明", ""))
    if not any(any(not is_placeholder(cell) for cell in row) for row in component_rows):
        findings.append(make_finding("medium", "component.missing", "缺少组件与交互说明", "关键组件的交互和约束未明确。", "至少补 1 行组件、交互说明和约束。"))
    else:
        passes.append("组件与交互说明已登记")

    responsive = sections.get("7. 响应式与端差异", "")
    responsive_fields = ["Web", "H5", "App", "后台"]
    filled_responsive = [field for field in responsive_fields if not is_placeholder(extract_bullet_value(responsive, field))]
    if not filled_responsive:
        findings.append(make_finding("medium", "responsive.empty", "缺少端差异说明", "无法判断不同端是否需要差异化设计。", "至少填写涉及的端和差异结论；不涉及可显式写无。"))
    else:
        passes.append("端差异说明已登记")

    assets = sections.get("8. 视觉资源与设计稿链接", "")
    asset_fields = ["本地设计源文件", "页面截图目录", "导出资源目录", "图标资源目录"]
    missing_assets = [field for field in asset_fields if is_placeholder(extract_bullet_value(assets, field))]
    if missing_assets:
        findings.append(make_finding("high", "assets.missing", "设计资产路径不完整", f"缺少字段：{', '.join(missing_assets)}。", "补齐本地 .fig、screens、exports、assets 路径。"))
    else:
        passes.append("设计资产路径已登记")

    screenshot_rows = extract_table_rows(sections.get("9. 页面截图索引", ""))
    valid_screenshot_rows = [row for row in screenshot_rows if len(row) >= 2 and any(not is_placeholder(cell) for cell in row)]
    if not valid_screenshot_rows:
        findings.append(make_finding("high", "screenshot_index.missing", "缺少页面截图索引", "主文档未建立页面状态到截图文件的映射。", "至少补 1 行页面/状态与截图文件映射。"))
    else:
        passes.append(f"页面截图索引存在 {len(valid_screenshot_rows)} 行")

    acceptance_items = extract_list_items(sections.get("10. 验收重点", ""))
    if not acceptance_items:
        findings.append(make_finding("medium", "acceptance.missing", "缺少验收重点", "测试和 UI 验收无法据此聚焦关键检查点。", "补至少 1 条验收重点。"))
    else:
        passes.append(f"验收重点存在 {len(acceptance_items)} 条")

    feature_slug = ui_doc_path.stem
    fig_file = ui_doc_path.with_suffix(".fig")
    design_dir = ui_doc_path.parent / feature_slug
    screens_dir = design_dir / "screens"
    assets_dir = design_dir / "assets"
    exports_dir = design_dir / "exports"

    if not fig_file.exists():
        findings.append(make_finding("high", "fig.missing", "缺少本地设计源文件", f"未找到 `{fig_file.name}`。", "保存本地设计源文件，例如 .fig，并与主文档同级放置。"))
    else:
        passes.append("本地设计源文件存在")

    if not screens_dir.exists():
        findings.append(make_finding("high", "screens.missing", "缺少截图目录", f"未找到 `{screens_dir}`。", "创建 screens 目录并保存页面截图。"))
    else:
        screen_files = list_files(screens_dir)
        if not screen_files:
            findings.append(make_finding("high", "screens.empty", "截图目录为空", "screens 目录存在但没有截图文件。", "导出关键页面和状态截图到 screens 目录。"))
        else:
            invalid_screen_files = [item.name for item in screen_files if not SCREENSHOT_NAME_RE.match(item.name)]
            if invalid_screen_files:
                findings.append(make_finding("medium", "screens.naming", "截图命名不符合规范", f"不合规文件：{', '.join(invalid_screen_files)}。", "使用 `page-{page-name}-{state}.png` 或 `page-{page-name}-{state}-{platform}.png`。"))
            else:
                passes.append(f"截图目录存在 {len(screen_files)} 个合规文件")

    for folder, code, title in [(assets_dir, "assets.dir_missing", "缺少图标资源目录"), (exports_dir, "exports.dir_missing", "缺少导出资源目录")]:
        if not folder.exists():
            findings.append(make_finding("low", code, title, f"未找到 `{folder}`。", "创建目录；即使暂时无文件，也保留标准结构。"))
        else:
            passes.append(f"{folder.name} 目录存在")

    if assets_dir.exists():
        invalid_assets = [item.name for item in list_files(assets_dir) if not (ASSET_NAME_RE.match(item.name) or ANNOT_NAME_RE.match(item.name))]
        if invalid_assets:
            findings.append(make_finding("low", "assets.naming", "资源文件命名不符合规范", f"不合规文件：{', '.join(invalid_assets)}。", "图标与位图使用 `asset-{name}.{ext}`，标注图使用 `annot-{page-name}-{topic}.png`。"))

    if exports_dir.exists():
        invalid_exports = [item.name for item in list_files(exports_dir) if not ASSET_NAME_RE.match(item.name)]
        if invalid_exports:
            findings.append(make_finding("low", "exports.naming", "导出资源命名不符合规范", f"不合规文件：{', '.join(invalid_exports)}。", "导出资源使用 `asset-{name}.{ext}`。"))

    high_count = sum(1 for finding in findings if finding.severity == "high")
    medium_count = sum(1 for finding in findings if finding.severity == "medium")
    if high_count >= 2 or any(finding.code in {"linkage.missing", "scope.missing", "states.missing", "assets.missing", "screenshot_index.missing", "fig.missing", "screens.missing", "screens.empty"} for finding in findings):
        decision = "BLOCK"
        risk = "high"
    elif high_count == 1 or medium_count >= 3:
        decision = "REVISE_BEFORE_REVIEW"
        risk = "medium" if high_count == 0 else "high"
    else:
        decision = "ALLOW_TO_REVIEW"
        risk = "low" if medium_count == 0 else "medium"

    return {"decision": decision, "normalized_decision": {"ALLOW_TO_REVIEW": "allow", "REVISE_BEFORE_REVIEW": "revise", "BLOCK": "block"}[decision], "risk": risk, "passes": passes, "findings": [finding.__dict__ for finding in findings]}


def render_markdown(report: dict, ui_path: str, issue: str | None) -> str:
    lines = [
        "# UI Design Review Report",
        "",
        f"- UI Doc: `{ui_path}`",
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
    lines.extend(["## Paste-Ready Comment", "", "状态：`ui-design-checker` 已完成。", "", f"- 结论：`{report['decision']}`", f"- 统一决策码：`{report['normalized_decision']}`", f"- 风险：`{report['risk']}`"])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- {finding['severity']}：{finding['title']}。{finding['advice']}")
    else:
        lines.append("- 结构化检查通过，当前未发现需要阻断设计交接的缺项。")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UI design handoff checks for template-based Markdown docs and local assets.")
    parser.add_argument("--ui", required=True, help="Path to UI design Markdown file")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    args = parser.parse_args()

    ui_path = Path(args.ui).resolve()
    markdown = read_text(ui_path)
    report = analyze_ui_design(markdown, ui_path)

    if args.format == "json":
        rendered = json.dumps({"ui": str(ui_path), "issue": args.issue, **report}, ensure_ascii=False, indent=2)
    else:
        rendered = render_markdown(report, str(ui_path), args.issue)

    if args.output:
        output_path = derive_output_path(ui_path) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
