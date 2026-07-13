#!/usr/bin/env python3
import argparse
import fnmatch
import json
import re
from pathlib import Path

try:
    from .project_structure_bootstrap import (
        APPLICATIONS_END,
        APPLICATIONS_START,
        load_layout,
        normalize_manifest,
        render_applications_table,
        validate_manifest,
    )
except ImportError:  # Support direct execution from the skill directory.
    from project_structure_bootstrap import (
        APPLICATIONS_END,
        APPLICATIONS_START,
        load_layout,
        normalize_manifest,
        render_applications_table,
        validate_manifest,
    )


CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def pattern_to_regex(pattern: str, placeholders: dict[str, str] | None = None) -> re.Pattern[str]:
    if placeholders is None:
        placeholders = load_layout()["artifact_placeholders"]
    expression = re.escape(pattern)
    for placeholder in sorted(placeholders, key=len, reverse=True):
        expression = expression.replace(re.escape(placeholder), placeholders[placeholder])
    expression = expression.replace(re.escape("**"), r".+")
    if "\\{" in expression or "\\}" in expression:
        raise ValueError(f"文档路径包含未知占位符：{pattern}")
    return re.compile(f"^{expression}$")


def finding(severity: str, code: str, path: str, message: str, target: str | None = None) -> dict:
    result = {"severity": severity, "code": code, "path": path, "message": message}
    if target:
        result["target"] = target
    return result


def check_zone_naming(workspace: Path, zone: dict, findings: list[dict]) -> None:
    root = workspace / zone["path"]
    if root.is_symlink():
        findings.append(finding("block", "zone.symlink", zone["path"], "受管区域不允许使用符号链接。"))
        return
    if zone.get("naming") != "kebab-case" or not zone.get("naming_scope"):
        return
    if not root.is_dir():
        return
    items = root.iterdir() if zone["naming_scope"] == "children" else root.rglob("*")
    for path in sorted(items):
        if path.name.startswith("."):
            continue
        candidate = path.name if path.is_dir() else path.name.split(".", 1)[0]
        if not KEBAB_RE.fullmatch(candidate):
            relative = path.relative_to(workspace).as_posix()
            findings.append(finding(
                "revise", "naming.noncanonical", relative,
                "非代码区域名称必须使用小写 kebab-case。", zone["path"],
            ))


def load_manifest(workspace: Path, layout: dict, findings: list[dict]) -> dict | None:
    relative = layout["manifest_path"]
    path = workspace / relative
    if not path.is_file():
        findings.append(finding("block", "manifest.missing", relative, "缺少项目结构索引，请先运行初始化器。"))
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifest, legacy = normalize_manifest(raw, layout)
        validate_manifest(manifest, layout)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        findings.append(finding("block", "manifest.invalid", relative, f"项目结构索引无效：{error}"))
        return None
    if legacy:
        findings.append(finding(
            "block", "manifest.version", relative,
            "旧版 manifest 已弃用，请运行初始化器并使用 --migrate 升级到 version 3。",
        ))
    return manifest


def matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def analyze(workspace: Path) -> dict:
    layout = load_layout()
    findings: list[dict] = []
    passes: list[str] = []
    manifest = load_manifest(workspace, layout, findings)

    for required in layout["required_files"]:
        if required == layout["manifest_path"]:
            continue
        if (workspace / required).is_file():
            passes.append(f"必备文件存在：{required}")
        else:
            findings.append(finding("block", "required.missing", required, "缺少项目级必备文件，请先运行初始化器。"))

    profiles = manifest["profiles"] if manifest else []
    applications = manifest["applications"] if manifest else []
    zones = list(layout["baseline_zones"])
    for profile_name in profiles:
        zones.extend(layout["profiles"][profile_name]["zones"])
    if manifest:
        zones.extend(manifest["additional_zones"])

    for application in applications:
        application_root = workspace / application["path"]
        if application_root.is_symlink():
            findings.append(finding(
                "block", "application.symlink", application["path"],
                "应用根目录不允许使用符号链接。",
            ))
            continue
        if not application_root.is_dir():
            findings.append(finding(
                "block", "application.missing", application["path"],
                "manifest 中登记的应用目录不存在。",
            ))
            continue
        for profile_name in application["profiles"]:
            for zone in layout["profiles"][profile_name]["zones"]:
                nested_zone = dict(zone)
                nested_zone["path"] = f"{application['path']}/{zone['path']}"
                nested_root = workspace / nested_zone["path"]
                if zone.get("bootstrap") and not nested_root.is_dir():
                    findings.append(finding(
                        "block", "application.zone_missing", nested_zone["path"],
                        "应用 profile 要求的源码区域不存在。",
                    ))
                check_zone_naming(workspace, nested_zone, findings)

    apps_root = workspace / "apps"
    if profiles == ["monorepo"] and apps_root.is_dir():
        registered_paths = {application["path"] for application in applications}
        for path in sorted(apps_root.iterdir()):
            relative = path.relative_to(workspace).as_posix()
            if (path.is_dir() or path.is_symlink()) and relative not in registered_paths:
                findings.append(finding(
                    "revise", "application.unregistered", relative,
                    "apps 下的应用未登记到 manifest 和项目说明。",
                    ".project-structure.json:applications",
                ))

    zone_roots = {zone["path"].split("/", 1)[0] for zone in zones}
    generated_roots = {zone["path"].split("/", 1)[0] for zone in layout["generated_zones"]}
    ignored_roots = set(layout["ignored_zones"])
    baseline_allowed_root_files = set(layout["allowed_root_files"])
    allowed_root_files = set(baseline_allowed_root_files)
    allowed_root_patterns = list(layout.get("allowed_root_patterns", []))
    prohibited_root_patterns = list(layout.get("prohibited_root_patterns", []))
    if manifest:
        allowed_root_files.update(manifest["allowed_root_files"])

    if workspace.is_dir():
        for path in sorted(workspace.iterdir()):
            name = path.name
            if path.is_symlink():
                findings.append(finding("block", "root_entry.symlink", name, "仓库根目录不允许使用符号链接。"))
                continue
            if path.is_dir():
                if name not in zone_roots | generated_roots | ignored_roots:
                    findings.append(finding(
                        "revise", "zone.unowned", name, "顶层目录没有 Owner 或用途定义。",
                        ".project-structure.json:additional_zones",
                    ))
                continue
            if not path.is_file():
                findings.append(finding("block", "root_entry.unsupported", name, "仓库根目录包含不支持的特殊文件类型。"))
                continue
            globally_allowed = name in baseline_allowed_root_files or matches_any(name, allowed_root_patterns)
            allowed = globally_allowed or name in allowed_root_files
            if not globally_allowed and matches_any(name, prohibited_root_patterns):
                findings.append(finding("block", "root_file.prohibited", name, "根目录包含可能泄露密钥或环境配置的文件。", ".gitignore"))
            elif not allowed:
                findings.append(finding(
                    "revise", "root_file.unowned", name, "普通文件不应直接放在仓库根目录。",
                    "已定义区域或 allowed_root_files",
                ))

    for zone in zones:
        check_zone_naming(workspace, zone, findings)

    placeholders = layout["artifact_placeholders"]
    patterns = [(item, pattern_to_regex(item["pattern"], placeholders)) for item in layout["document_artifacts"]]
    docs_root = workspace / "docs"
    if docs_root.is_dir():
        for path in sorted(item for item in docs_root.rglob("*") if item.is_file()):
            relative = path.relative_to(workspace).as_posix()
            if path.name == ".gitkeep":
                continue
            if not any(regex.fullmatch(relative) for _, regex in patterns):
                findings.append(finding(
                    "revise", "document.noncanonical", relative, "文档资产不符合产物索引。",
                    "references/project-layout.json:document_artifacts",
                ))
                continue
            if path.suffix.lower() == ".md":
                content = path.read_text(encoding="utf-8", errors="replace")
                if not CHINESE_RE.search(content):
                    findings.append(finding("revise", "document.language_baseline", relative, "项目 Markdown 文档未包含中文内容。"))

    overview_path = workspace / "docs/project/project-overview.md"
    if manifest and overview_path.is_file():
        overview = overview_path.read_text(encoding="utf-8", errors="replace")
        expected_table = render_applications_table(applications)
        start = overview.find(APPLICATIONS_START)
        end = overview.find(APPLICATIONS_END, start + len(APPLICATIONS_START)) if start != -1 else -1
        actual_table = overview[start:end + len(APPLICATIONS_END)] if end != -1 else ""
        if actual_table != expected_table:
            findings.append(finding(
                "revise", "overview.applications", "docs/project/project-overview.md",
                "项目说明中的应用清单与 manifest 不一致，请重新运行初始化器同步。",
            ))

    decision = "allow"
    if any(item["severity"] == "block" for item in findings):
        decision = "block"
    elif findings:
        decision = "revise"
    return {
        "decision": decision,
        "profiles": profiles,
        "applications": applications,
        "passes": passes,
        "findings": findings,
    }


def render_text(report: dict) -> str:
    profiles = ",".join(report["profiles"]) or "unknown"
    lines = [f"decision: {report['decision']}", f"profiles: {profiles}"]
    lines.extend(f"PASS: {item}" for item in report["passes"])
    for item in report["findings"]:
        target = f" -> {item['target']}" if item.get("target") else ""
        lines.append(f"{item['severity'].upper()}: {item['path']} - {item['message']}{target}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查整个仓库的文件落位、目录索引和文档命名。")
    parser.add_argument("--workspace", default=".", help="项目仓库根目录")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--fail-on", choices=("revise", "block"))
    args = parser.parse_args()

    try:
        report = analyze(Path(args.workspace).resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"project-structure-checker failed: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else render_text(report))

    if args.fail_on == "revise" and report["decision"] in {"revise", "block"}:
        return 1
    if args.fail_on == "block" and report["decision"] == "block":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
