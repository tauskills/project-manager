#!/usr/bin/env python3
import argparse
import fnmatch
import json
import re
from pathlib import Path, PurePosixPath


SKILL_ROOT = Path(__file__).resolve().parent.parent
LAYOUT_PATH = SKILL_ROOT / "references" / "project-layout.json"
OVERVIEW_TEMPLATE = SKILL_ROOT / "assets" / "project-overview-template.md"
ZONE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)*$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
APPLICATION_PATH_RE = re.compile(r"^apps/[a-z0-9]+(?:-[a-z0-9]+)*$")
GLOB_CHARS = frozenset("*?[]")
APPLICATIONS_START = "<!-- project-structure:applications:start -->"
APPLICATIONS_END = "<!-- project-structure:applications:end -->"


def load_layout() -> dict:
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    if not isinstance(layout, dict) or layout.get("version") != 3:
        raise ValueError("project-layout.json 必须是 version 3 对象。")
    return layout


def detect_profiles(workspace: Path, layout: dict) -> list[str]:
    root_files = [item.name for item in workspace.iterdir() if item.is_file()] if workspace.is_dir() else []
    matches = [
        name
        for name, profile in layout["profiles"].items()
        if name != "generic" and any(
            fnmatch.fnmatchcase(filename, pattern)
            for filename in root_files
            for pattern in profile["marker_patterns"]
        )
    ]
    if "monorepo" in matches:
        return ["monorepo"]
    return matches or [layout["defaults"]["profile"]]


def detect_applications(workspace: Path, layout: dict) -> list[dict]:
    apps_root = workspace / "apps"
    if not apps_root.is_dir() or apps_root.is_symlink():
        return []
    applications = []
    for path in sorted(apps_root.iterdir()):
        if not path.is_dir() or path.is_symlink():
            continue
        if not SLUG_RE.fullmatch(path.name):
            raise ValueError(f"无法自动登记非 kebab-case 应用目录：apps/{path.name}")
        profiles = detect_profiles(path, layout)
        if profiles == ["monorepo"]:
            raise ValueError(f"应用目录不能嵌套 monorepo profile：apps/{path.name}")
        applications.append({
            "name": path.name,
            "path": f"apps/{path.name}",
            "profiles": profiles,
            "owner": "engineering",
            "purpose": f"{path.name} application",
        })
    return applications


def normalize_manifest(data: object, _layout: dict) -> tuple[dict, bool]:
    if not isinstance(data, dict):
        raise ValueError(".project-structure.json 根节点必须是对象。")
    if data.get("version") == 1:
        profile = data.get("profile")
        if not isinstance(profile, str):
            raise ValueError("version 1 manifest 缺少字符串 profile。")
        normalized = {
            "version": 3,
            "profiles": [profile],
            "applications": [],
            "additional_zones": data.get("additional_zones", []),
            "allowed_root_files": data.get("allowed_root_files", []),
        }
        return normalized, True
    if data.get("version") == 2:
        normalized = dict(data)
        normalized["version"] = 3
        normalized["applications"] = []
        return normalized, True
    if data.get("version") != 3:
        raise ValueError("manifest version 必须是 1、2 或 3。")
    return data, False


def validate_profiles(profiles: list[str], layout: dict) -> list[str]:
    if not profiles:
        raise ValueError("至少选择一个 profile。")
    unknown = [name for name in profiles if name not in layout["profiles"]]
    if unknown:
        raise ValueError(f"未知 profile：{', '.join(unknown)}")
    selected = list(dict.fromkeys(profiles))
    if "generic" in selected and len(selected) > 1:
        raise ValueError("generic 不能与其他 profile 组合。")
    if "monorepo" in selected and len(selected) > 1:
        raise ValueError("monorepo 不能与应用技术 profile 组合；请使用 applications。")
    return selected


def validate_manifest(manifest: dict, layout: dict) -> None:
    allowed_keys = {"version", "profiles", "applications", "additional_zones", "allowed_root_files"}
    unknown_keys = sorted(set(manifest) - allowed_keys)
    if unknown_keys:
        raise ValueError(f"manifest 包含未知字段：{', '.join(unknown_keys)}")
    if manifest.get("version") != 3:
        raise ValueError("manifest version 必须是 3。")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, list) or not all(isinstance(item, str) for item in profiles):
        raise ValueError("profiles 必须是字符串数组。")
    if len(profiles) != len(set(profiles)):
        raise ValueError("profiles 不允许重复。")
    validate_profiles(profiles, layout)
    applications = manifest.get("applications")
    if not isinstance(applications, list):
        raise ValueError("applications 必须是数组。")
    if applications and profiles != ["monorepo"]:
        raise ValueError("包含 applications 时，仓库 profiles 必须且只能是 monorepo。")
    seen_application_names: set[str] = set()
    seen_application_paths: set[str] = set()
    for index, application in enumerate(applications):
        if not isinstance(application, dict):
            raise ValueError(f"applications[{index}] 必须是对象。")
        if set(application) != {"name", "path", "profiles", "owner", "purpose"}:
            raise ValueError(
                f"applications[{index}] 必须且只能包含 name、path、profiles、owner、purpose。"
            )
        name = application["name"]
        path = application["path"]
        app_profiles = application["profiles"]
        if not isinstance(name, str) or not SLUG_RE.fullmatch(name):
            raise ValueError(f"applications[{index}] name 必须使用 kebab-case。")
        if not isinstance(path, str) or not APPLICATION_PATH_RE.fullmatch(path) or path != f"apps/{name}":
            raise ValueError(f"applications[{index}] path 必须是 apps/{name}。")
        if not isinstance(app_profiles, list) or not all(isinstance(item, str) for item in app_profiles):
            raise ValueError(f"applications[{index}] profiles 必须是字符串数组。")
        if len(app_profiles) != len(set(app_profiles)):
            raise ValueError(f"applications[{index}] profiles 不允许重复。")
        validate_profiles(app_profiles, layout)
        if "monorepo" in app_profiles:
            raise ValueError(f"applications[{index}] 不能使用 monorepo profile。")
        if not all(
            isinstance(application[key], str) and application[key].strip()
            for key in ("owner", "purpose")
        ):
            raise ValueError(f"applications[{index}] 缺少有效的 owner 或 purpose。")
        if name in seen_application_names or path in seen_application_paths:
            raise ValueError(f"applications[{index}] name 或 path 重复。")
        seen_application_names.add(name)
        seen_application_paths.add(path)
    zones = manifest.get("additional_zones")
    if not isinstance(zones, list):
        raise ValueError("additional_zones 必须是数组。")
    seen_paths: set[str] = set()
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise ValueError(f"additional_zones[{index}] 必须是对象。")
        if set(zone) - {"path", "owner", "purpose", "naming", "naming_scope"}:
            raise ValueError(f"additional_zones[{index}] 包含未知字段。")
        if not all(isinstance(zone.get(key), str) and zone[key].strip() for key in ("path", "owner", "purpose")):
            raise ValueError(f"additional_zones[{index}] 缺少有效的 path、owner 或 purpose。")
        path = zone["path"]
        pure = PurePosixPath(path)
        if not ZONE_RE.fullmatch(path) or ".." in pure.parts or "//" in path:
            raise ValueError(f"additional_zones[{index}] path 不是规范的安全相对路径：{path}")
        if path in seen_paths:
            raise ValueError(f"additional_zones path 重复：{path}")
        seen_paths.add(path)
        if "naming_scope" in zone and zone["naming_scope"] not in {"all", "children"}:
            raise ValueError(f"additional_zones[{index}] naming_scope 无效。")
    root_files = manifest.get("allowed_root_files")
    if not isinstance(root_files, list) or not all(isinstance(item, str) and item for item in root_files):
        raise ValueError("allowed_root_files 必须是非空文件名数组。")
    if len(root_files) != len(set(root_files)):
        raise ValueError("allowed_root_files 不允许重复。")
    for name in root_files:
        if "/" in name or "\\" in name or any(char in name for char in GLOB_CHARS):
            raise ValueError(f"allowed_root_files 只允许根目录字面文件名：{name}")


def safe_target(workspace: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"不安全的相对路径：{relative}")
    root = workspace.resolve()
    target = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"受管路径不允许使用符号链接：{current}")
    if not target.resolve(strict=False).is_relative_to(root):
        raise ValueError(f"目标路径超出项目仓库：{relative}")
    return target


def merge_gitignore(existing: str, patterns: list[str]) -> str:
    lines = existing.splitlines()
    missing = [pattern for pattern in patterns if pattern not in lines]
    if not missing:
        return existing
    prefix = "\n" if existing and not existing.endswith("\n\n") else ""
    if existing and not existing.endswith("\n"):
        prefix = "\n\n"
    block = "# project-structure-governance\n" + "\n".join(missing) + "\n"
    return existing + prefix + block


def parse_application_specs(specs: list[str]) -> list[dict]:
    applications = []
    for spec in specs:
        name, separator, raw_profiles = spec.partition("=")
        profiles = [item for item in raw_profiles.split(",") if item]
        if not separator or not name or not profiles:
            raise ValueError(f"application 格式必须是 name=profile[,profile]：{spec}")
        applications.append({
            "name": name,
            "path": f"apps/{name}",
            "profiles": profiles,
            "owner": "engineering",
            "purpose": f"{name} application",
        })
    return applications


def preserve_application_metadata(requested: list[dict], existing: list[dict]) -> list[dict]:
    existing_by_path = {application["path"]: application for application in existing}
    merged = []
    for application in requested:
        previous = existing_by_path.get(application["path"])
        if previous and previous["name"] == application["name"]:
            application = dict(application)
            application["owner"] = previous["owner"]
            application["purpose"] = previous["purpose"]
        merged.append(application)
    return merged


def markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\r\n", "<br>").replace("\n", "<br>")


def render_applications_table(applications: list[dict]) -> str:
    lines = [
        APPLICATIONS_START,
        "| 应用 | 路径 | 技术 Profile | Owner | 用途 |",
        "| --- | --- | --- | --- | --- |",
    ]
    if applications:
        for application in applications:
            profiles = ", ".join(application["profiles"])
            lines.append(
                f"| {markdown_cell(application['name'])} | `{application['path']}` | "
                f"{markdown_cell(profiles)} | {markdown_cell(application['owner'])} | "
                f"{markdown_cell(application['purpose'])} |"
            )
    else:
        lines.append("| 无（单应用仓库） | - | - | - | - |")
    lines.append(APPLICATIONS_END)
    return "\n".join(lines)


def sync_applications_table(content: str, applications: list[dict]) -> str:
    table = render_applications_table(applications)
    if content.count(APPLICATIONS_START) > 1 or content.count(APPLICATIONS_END) > 1:
        raise ValueError("project-overview.md 包含重复的应用清单标记。")
    start = content.find(APPLICATIONS_START)
    end = content.find(APPLICATIONS_END)
    if (start == -1) != (end == -1) or (start != -1 and end < start):
        raise ValueError("project-overview.md 的应用清单标记不完整。")
    if start != -1:
        end += len(APPLICATIONS_END)
        return content[:start] + table + content[end:]
    separator = "\n" if content.endswith("\n") else "\n\n"
    return content + separator + "## 应用清单\n\n" + table + "\n"


def bootstrap(
    workspace: Path,
    profiles: str | list[str] = "auto",
    *,
    applications: list[dict] | None = None,
    migrate: bool = False,
    dry_run: bool = False,
    keep_empty: bool = False,
    manage_gitignore: bool = True,
) -> list[tuple[str, str]]:
    layout = load_layout()
    if workspace.is_symlink():
        raise ValueError(f"workspace 不允许是符号链接：{workspace}")
    if workspace.exists() and not workspace.is_dir():
        raise ValueError(f"workspace 不是目录：{workspace}")

    manifest_relative = layout["manifest_path"]
    manifest_path = safe_target(workspace, manifest_relative)
    existing_manifest: dict | None = None
    legacy_manifest = False
    if manifest_path.exists():
        if not manifest_path.is_file():
            raise ValueError(f"目标路径存在但不是文件：{manifest_path}")
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"现有 manifest 不是有效 JSON：{error}") from error
        existing_manifest, legacy_manifest = normalize_manifest(raw_manifest, layout)

    requested_applications = applications
    detected_applications = (
        detect_applications(workspace, layout)
        if applications is None and existing_manifest is None
        else []
    )
    selected_applications = (
        requested_applications
        if requested_applications is not None
        else (existing_manifest["applications"] if existing_manifest else detected_applications)
    )
    if requested_applications is not None and existing_manifest:
        selected_applications = preserve_application_metadata(
            selected_applications, existing_manifest["applications"]
        )
    requested = [profiles] if isinstance(profiles, str) else profiles
    if requested == ["auto"]:
        if selected_applications:
            selected = ["monorepo"]
        else:
            selected = existing_manifest["profiles"] if existing_manifest else detect_profiles(workspace, layout)
    else:
        if "auto" in requested:
            raise ValueError("auto 不能与显式 profile 组合。")
        selected = requested
    selected = validate_profiles(selected, layout)

    if existing_manifest:
        existing_profiles = validate_profiles(existing_manifest.get("profiles", []), layout)
        if legacy_manifest and not migrate:
            raise ValueError("检测到旧版 manifest；使用 --migrate 升级到 version 3。")
        if existing_profiles != selected and not migrate:
            raise ValueError(
                f"现有 profiles 为 {existing_profiles}，请求为 {selected}；使用 --migrate 明确迁移。"
            )
        if requested_applications is not None and existing_manifest["applications"] != selected_applications and not migrate:
            raise ValueError("现有 applications 与请求不一致；使用 --migrate 明确变更。")
        manifest = dict(existing_manifest)
        manifest["version"] = 3
        manifest["profiles"] = selected
        manifest["applications"] = selected_applications
    else:
        manifest = {
            "version": 3,
            "profiles": selected,
            "applications": selected_applications,
            "additional_zones": [],
            "allowed_root_files": [],
        }
    validate_manifest(manifest, layout)

    zones = list(layout["baseline_zones"])
    for name in selected:
        zones.extend(layout["profiles"][name]["zones"])
    directory_paths = [zone["path"] for zone in zones if zone.get("bootstrap")]
    directory_paths.extend(layout["document_directories"])
    for application in selected_applications:
        directory_paths.append(application["path"])
        for profile_name in application["profiles"]:
            directory_paths.extend(
                f"{application['path']}/{zone['path']}"
                for zone in layout["profiles"][profile_name]["zones"]
                if zone.get("bootstrap")
            )
    directory_paths = list(dict.fromkeys(directory_paths))

    # Complete every validation before the first write.
    directory_targets: list[tuple[str, Path, str]] = []
    for relative in directory_paths:
        target = safe_target(workspace, relative)
        if target.exists() and not target.is_dir():
            raise ValueError(f"目标路径存在但不是目录：{target}")
        directory_targets.append((relative, target, "skipped" if target.is_dir() else "created"))

    overview_relative = "docs/project/project-overview.md"
    overview_path = safe_target(workspace, overview_relative)
    if overview_path.exists() and not overview_path.is_file():
        raise ValueError(f"目标路径存在但不是文件：{overview_path}")
    gitignore_path = safe_target(workspace, ".gitignore")
    if gitignore_path.exists() and not gitignore_path.is_file():
        raise ValueError(f"目标路径存在但不是文件：{gitignore_path}")

    manifest_content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    manifest_changed = bool(existing_manifest) and (
        legacy_manifest
        or existing_manifest["profiles"] != selected
        or existing_manifest["applications"] != selected_applications
    )
    manifest_status = "updated" if manifest_changed else ("skipped" if existing_manifest else "written")
    overview_existing = (
        overview_path.read_text(encoding="utf-8")
        if overview_path.is_file()
        else OVERVIEW_TEMPLATE.read_text(encoding="utf-8")
    )
    overview_content = sync_applications_table(overview_existing, selected_applications)
    overview_status = (
        "updated" if overview_path.is_file() and overview_content != overview_existing
        else ("skipped" if overview_path.is_file() else "written")
    )
    gitignore_existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    gitignore_content = merge_gitignore(gitignore_existing, layout["gitignore_patterns"])
    gitignore_status = "skipped" if gitignore_content == gitignore_existing else ("updated" if gitignore_existing else "written")

    results: list[tuple[str, str]] = [("+".join(selected), "profiles")]
    results.extend((relative, status) for relative, _, status in directory_targets)
    results.extend([(manifest_relative, manifest_status), (overview_relative, overview_status)])
    if manage_gitignore:
        results.append((".gitignore", gitignore_status))

    if dry_run:
        return [(path, f"planned-{status}" if status not in {"skipped", "profiles"} else status) for path, status in results]

    workspace.mkdir(parents=True, exist_ok=True)
    for _, target, status in directory_targets:
        target.mkdir(parents=True, exist_ok=True)
        if keep_empty and status == "created":
            (target / ".gitkeep").touch(exist_ok=True)
    if manifest_status != "skipped":
        manifest_path.write_text(manifest_content, encoding="utf-8")
    if overview_status != "skipped":
        overview_path.write_text(overview_content, encoding="utf-8")
    if manage_gitignore and gitignore_status != "skipped":
        gitignore_path.write_text(gitignore_content, encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化项目目录、项目索引和忽略规则。")
    parser.add_argument("--workspace", default=".", help="项目仓库根目录")
    parser.add_argument("--profile", action="append", dest="profiles", help="可重复指定组合 profile；默认自动识别")
    parser.add_argument(
        "--application", action="append", default=[], metavar="NAME=PROFILE[,PROFILE]",
        help="定义 apps/NAME 下的应用及技术 profile；可重复指定",
    )
    parser.add_argument("--migrate", action="store_true", help="明确升级旧 manifest 或改变 profiles")
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不写文件")
    parser.add_argument("--keep-empty", action="store_true", help="在初始化目录中创建 .gitkeep")
    parser.add_argument("--no-gitignore", action="store_true", help="不创建或合并 .gitignore 基线")
    args = parser.parse_args()

    try:
        applications = parse_application_specs(args.application) if args.application else None
        results = bootstrap(
            Path(args.workspace), args.profiles or "auto", applications=applications, migrate=args.migrate,
            dry_run=args.dry_run, keep_empty=args.keep_empty, manage_gitignore=not args.no_gitignore,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"project-structure-bootstrap failed: {error}\n")

    print("project-structure-bootstrap plan" if args.dry_run else "project-structure-bootstrap complete")
    for path, status in results:
        print(f"- [{status}] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
