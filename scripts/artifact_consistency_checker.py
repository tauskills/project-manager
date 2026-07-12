#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


PLACEHOLDER_VALUES = {"", "-", "—", "/", "待补充", "todo", "tbd", "n/a"}
STAGES = ("intake", "design", "development", "qa", "release", "closure")
STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}


@dataclass
class Finding:
    severity: str
    code: str
    title: str
    detail: str
    advice: str


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def is_placeholder(value: str) -> bool:
    return normalize_text(value).strip("`").lower() in PLACEHOLDER_VALUES


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_bullet_value(section_body: str, label: str) -> str:
    pattern = re.compile(rf"^[ \t]*-[ \t]*{re.escape(label)}[ \t]*[:：][ \t]*(.*)$", re.MULTILINE)
    match = pattern.search(section_body)
    return match.group(1).strip() if match else ""


def split_sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, re.MULTILINE))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        sections[match.group(1).strip()] = markdown[start:end].strip()
    return sections


def make_finding(severity: str, code: str, title: str, detail: str, advice: str) -> Finding:
    return Finding(severity=severity, code=code, title=title, detail=detail, advice=advice)


def find_docs_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if parent.name == "docs":
            return parent
    return None


def derive_output_path(feature_doc: Path) -> Path:
    docs_root = find_docs_root(feature_doc)
    if docs_root is None:
        raise ValueError("`--output auto` requires the feature doc to live under a `docs/` directory.")
    return docs_root / "review" / "artifact-consistency" / f"{feature_doc.stem}.artifact-consistency.generated.md"


def extract_paths(markdown: str) -> list[str]:
    return re.findall(r"`(docs/[^`]+)`", markdown)


def is_template_path(value: str) -> bool:
    return "{" in value or "}" in value


def check_doc_exists(path: Path, findings: list[Finding], passes: list[str], label: str) -> None:
    if path.exists():
        passes.append(f"{label} 存在")
    else:
        findings.append(make_finding("high", f"{label}.missing", f"{label} 缺失", f"未找到 `{path}`。", f"补齐 {label}，并确保路径可被仓库内其他文档引用。"))


def analyze_feature(workspace: Path, feature_slug: str, stage: str = "development") -> dict:
    findings: list[Finding] = []
    passes: list[str] = []

    prd = workspace / f"docs/product/{feature_slug}.md"
    ui = workspace / f"docs/design/{feature_slug}.md"
    fig = workspace / f"docs/design/{feature_slug}.fig"
    screens = workspace / f"docs/design/{feature_slug}/screens"
    dev = workspace / f"docs/development/{feature_slug}.md"
    schema = workspace / f"docs/development/schema/{feature_slug}.sql"
    openapi = workspace / "docs/development/openapi/openapi.yaml"
    testcase = workspace / f"docs/testing/{feature_slug}-test-cases.md"
    testreport = workspace / f"docs/testing/{feature_slug}-test-report.md"
    retro = workspace / f"docs/retrospective/{feature_slug}-retro.md"

    required_artifacts = [
        ("PRD", prd, "intake"),
        ("UI 设计文档", ui, "design"),
        ("UI 源文件", fig, "design"),
        ("技术文档", dev, "development"),
        ("Schema", schema, "development"),
        ("OpenAPI", openapi, "development"),
        ("测试用例", testcase, "development"),
        ("测试报告", testreport, "release"),
        ("复盘文档", retro, "closure"),
    ]
    for label, path, required_stage in required_artifacts:
        if STAGE_ORDER[stage] < STAGE_ORDER[required_stage]:
            continue
        check_doc_exists(path, findings, passes, label)

    if STAGE_ORDER[stage] >= STAGE_ORDER["design"]:
        if screens.exists() and any(screens.iterdir()):
            passes.append("UI screens 目录存在且非空")
        else:
            findings.append(make_finding("high", "ui.screens_missing", "UI 页面截图缺失", f"未找到非空截图目录 `{screens}`。", "导出关键页面和状态截图到 screens 目录。"))

    docs_to_check = [path for path in [prd, ui, dev, testcase, retro] if path.exists()]
    referenced = {
        "PRD": f"docs/product/{feature_slug}.md",
        "UI": f"docs/design/{feature_slug}.md",
        "Development": f"docs/development/{feature_slug}.md",
        "OpenAPI": "docs/development/openapi/openapi.yaml",
        "Schema": f"docs/development/schema/{feature_slug}.sql",
        "Test Cases": f"docs/testing/{feature_slug}-test-cases.md",
        "Test Report": f"docs/testing/{feature_slug}-test-report.md",
        "Retrospective": f"docs/retrospective/{feature_slug}-retro.md",
    }

    for doc in docs_to_check:
        content = read_text(doc)
        found_paths = {path for path in extract_paths(content) if not is_template_path(path)}
        doc_label = str(doc.relative_to(workspace))
        for name, rel in referenced.items():
            if doc.name == Path(rel).name:
                continue
            if name in {"Test Report", "Retrospective"} and doc != retro:
                continue
            if doc == retro and name == "Retrospective":
                continue
            if doc == testcase and name == "Test Cases":
                continue
            if doc == prd and name in {"PRD", "Test Report", "Retrospective"}:
                continue
            if doc == ui and name in {"UI", "Schema", "Test Report", "Retrospective"}:
                continue
            if doc == dev and name in {"Development", "Test Report", "Retrospective"}:
                continue
            if rel not in found_paths:
                findings.append(
                    make_finding(
                        "medium",
                        f"refs.{doc.stem}.{name.lower().replace(' ', '_')}",
                        f"{doc_label} 缺少关联引用",
                        f"未引用 `{rel}`。",
                        f"在 `{doc_label}` 中补齐对 {name} 的本地路径引用。",
                    )
                )

        for rel_path in found_paths:
            target = workspace / rel_path
            if not target.exists():
                findings.append(
                    make_finding(
                        "high",
                        f"path.broken.{doc.stem}",
                        f"{doc_label} 存在失效路径",
                        f"引用路径 `{rel_path}` 在仓库内不存在。",
                        "修正文档中的路径，或补齐被引用文件。",
                    )
                )

    high_count = sum(1 for item in findings if item.severity == "high")
    medium_count = sum(1 for item in findings if item.severity == "medium")
    if high_count >= 2 or any(item.code in {"ui.screens_missing"} or item.code.endswith(".missing") for item in findings):
        decision = "BLOCK"
        risk = "high"
    elif high_count == 1 or medium_count >= 4:
        decision = "REVISE_BEFORE_REVIEW"
        risk = "medium" if high_count == 0 else "high"
    else:
        decision = "ALLOW_TO_REVIEW"
        risk = "low" if medium_count == 0 else "medium"

    return {
        "stage": stage,
        "decision": decision,
        "normalized_decision": {"ALLOW_TO_REVIEW": "allow", "REVISE_BEFORE_REVIEW": "revise", "BLOCK": "block"}[decision],
        "risk": risk,
        "passes": passes,
        "findings": [item.__dict__ for item in findings],
    }


def render_markdown(report: dict, workspace: str, feature_slug: str, issue: str | None) -> str:
    lines = [
        "# Artifact Consistency Report",
        "",
        f"- Workspace: `{workspace}`",
        f"- Feature: `{feature_slug}`",
        f"- Issue: `{issue or 'N/A'}`",
        f"- Stage: `{report['stage']}`",
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
    lines.extend(["## Paste-Ready Comment", "", "状态：`artifact-consistency-checker` 已完成。", "", f"- 结论：`{report['decision']}`", f"- 统一决策码：`{report['normalized_decision']}`", f"- 风险：`{report['risk']}`"])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- {finding['severity']}：{finding['title']}。{finding['advice']}")
    else:
        lines.append("- 结构化一致性检查通过，当前未发现跨文档引用或产物缺失问题。")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cross-artifact consistency checks for a feature slug.")
    parser.add_argument("--workspace", default=".", help="Business repo root where docs/ live")
    parser.add_argument("--feature", required=True, help="Stable feature slug, for example payment-confirmation")
    parser.add_argument("--issue", help="Optional issue identifier")
    parser.add_argument("--stage", choices=STAGES, default="development", help="Lifecycle stage whose required artifacts should be checked")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional file path to save rendered report, or `auto` for canonical docs/review output")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    report = analyze_feature(workspace, args.feature, args.stage)
    marker = workspace / f"docs/product/{args.feature}.md"
    if args.format == "json":
        rendered = json.dumps({"workspace": str(workspace), "feature": args.feature, "issue": args.issue, **report}, ensure_ascii=False, indent=2)
    else:
        rendered = render_markdown(report, str(workspace), args.feature, args.issue)

    if args.output:
        output_path = derive_output_path(marker) if args.output == "auto" else Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
