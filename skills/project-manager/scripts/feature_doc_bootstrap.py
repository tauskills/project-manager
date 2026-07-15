#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

try:
    from .document_bundle import write_bundle
except ImportError:  # Support direct execution from the skill directory.
    from document_bundle import write_bundle


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "references" / "templates"

OPENAPI_STUB = """openapi: 3.1.0
info:
  title: {feature_slug}
  version: 0.1.0
paths: {{}}
"""

TEMPLATE_MAPPINGS = {
    "prd": ("prd-template.md", "docs/product/{feature_slug}", ["change-log", "basic-info", "background-and-goals", "users-and-scenarios", "scope", "main-flow", "states-and-errors", "non-functional-requirements", "acceptance-criteria", "dependencies-and-risks", "revision-history"]),
    "ui": ("ui-design-template.md", "docs/design/{feature_slug}", ["change-log", "basic-info", "design-goals", "pages-and-entry-points", "key-flows", "state-design", "components-and-interactions", "responsive-design", "visual-assets", "screenshot-index", "acceptance-focus", "revision-history"]),
    "development": ("architecture-design-template.md", "docs/development/{feature_slug}", ["basic-info", "change-log", "background-and-goals", "scope-and-impact", "system-boundaries", "technology-selection", "implementation-strategy", "api-and-schema", "ownership", "risks", "test-release-rollback", "conclusion"]),
    "testing": ("test-case-template.md", "docs/testing/{feature_slug}/test-cases", ["change-log", "basic-info", "test-scope", "test-focus", "environment-and-data", "test-cases", "regression-and-smoke", "risks-and-blockers", "revision-history"]),
    "test-report": ("test-report-template.md", "docs/testing/{feature_slug}/test-report", ["basic-info", "execution-summary", "defects-and-blockers", "regression-and-smoke", "test-conclusion"]),
    "retrospective": ("retrospective-template.md", "docs/retrospective/{feature_slug}", ["change-log", "basic-info", "goals-and-results", "timeline", "what-went-well", "root-causes", "risks-and-exceptions", "improvement-actions", "follow-up", "revision-history"]),
}

DIRECTORIES = [
    "docs/product/{feature_slug}",
    "docs/design/{feature_slug}/pages",
    "docs/design/{feature_slug}/flows",
    "docs/design/{feature_slug}/states",
    "docs/design/{feature_slug}/screens",
    "docs/design/{feature_slug}/assets",
    "docs/design/{feature_slug}/exports",
    "docs/development/{feature_slug}/openapi",
    "docs/development/{feature_slug}/schema",
    "docs/development/{feature_slug}/notes",
    "docs/testing/{feature_slug}/test-cases",
    "docs/testing/{feature_slug}/test-report",
    "docs/retrospective/{feature_slug}",
]

EXTRA_FILES = {
    "docs/design/{feature_slug}/pages/001-overview.md": "# 页面设计目录\n\n- 功能：`{feature-slug}`\n- 页面清单：待补充\n",
    "docs/design/{feature_slug}/flows/001-overview.md": "# 交互流程目录\n\n- 功能：`{feature-slug}`\n- 流程清单：待补充\n",
    "docs/design/{feature_slug}/states/001-overview.md": "# 状态设计目录\n\n- 功能：`{feature-slug}`\n- 状态清单：待补充\n",
    "docs/design/{feature_slug}/assets/design-source.fig": "",
    "docs/development/{feature_slug}/openapi/001-openapi.yaml": OPENAPI_STUB,
    "docs/development/{feature_slug}/schema/001-schema.sql": "-- schema stub for {feature_slug}\n",
    "docs/development/{feature_slug}/notes/001-overview.md": "# 开发记录目录\n\n- 功能：`{feature-slug}`\n- 前后端实现记录：待补充\n",
    "docs/testing/{feature_slug}/001-overview.md": "# 测试文档目录\n\n- 功能：`{feature-slug}`\n- 测试用例：`docs/testing/{feature-slug}/test-cases/`\n- 测试报告：`docs/testing/{feature-slug}/test-report/`\n",
    "docs/project/project-status.yaml": (TEMPLATE_DIR / "project-status-template.yaml").read_text(encoding="utf-8"),
}

LEGACY_PATHS = [
    "docs/product/{feature_slug}.md",
    "docs/design/{feature_slug}.md",
    "docs/design/{feature_slug}.fig",
    "docs/development/{feature_slug}.md",
    "docs/testing/{feature_slug}-test-cases.md",
    "docs/testing/{feature_slug}-test-report.md",
    "docs/retrospective/{feature_slug}-retro.md",
]


def ensure_ascii_slug(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    if not normalized:
        raise ValueError("feature slug must contain at least one ASCII letter or digit")
    return normalized


def render_template(text: str, feature_slug: str, issue_key: str | None) -> str:
    rendered = text.replace("{feature-slug}", feature_slug)
    rendered = rendered.replace("{feature_slug}", feature_slug)
    if issue_key:
        rendered = rendered.replace("{issue-key}", issue_key)
        rendered = rendered.replace("{issue_key}", issue_key)
    return rendered


def write_if_missing(path: Path, content: str, overwrite: bool) -> str:
    if path.exists() and not overwrite:
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def load_reference_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def bootstrap(workspace: Path, feature_slug: str, issue_key: str | None, overwrite: bool) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    legacy = [workspace / pattern.format(feature_slug=feature_slug) for pattern in LEGACY_PATHS]
    existing_legacy = [path for path in legacy if path.exists()]
    if existing_legacy:
        paths = ", ".join(str(path.relative_to(workspace)) for path in existing_legacy)
        raise ValueError(f"检测到旧版扁平文档：{paths}。请先按总分式目录规范拆分并更新引用。")

    for directory in DIRECTORIES:
        resolved = workspace / directory.format(feature_slug=feature_slug)
        resolved.mkdir(parents=True, exist_ok=True)
        results.append((str(resolved), "dir"))

    for _, (template_name, target_pattern, chapter_slugs) in TEMPLATE_MAPPINGS.items():
        target = workspace / target_pattern.format(feature_slug=feature_slug)
        template = render_template(load_reference_template(template_name), feature_slug, issue_key)
        results.extend(write_bundle(target, template, chapter_slugs, overwrite))

    for pattern, raw_content in EXTRA_FILES.items():
        target = workspace / pattern.format(feature_slug=feature_slug)
        content = render_template(raw_content, feature_slug, issue_key)
        # Contracts, design sources, schemas, and project state are never overwritten implicitly.
        protected = {"docs/project/project-status.yaml"} | {
            item for item in EXTRA_FILES if item.endswith((".fig", ".yaml", ".sql"))
        }
        allow_overwrite = overwrite and pattern not in protected
        status = write_if_missing(target, content, allow_overwrite)
        results.append((str(target), status))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap feature-level documentation and design asset skeleton.")
    parser.add_argument("--feature", required=True, help="Stable feature slug, for example payment-confirmation")
    parser.add_argument("--workspace", default=".", help="Business repo root where docs/ should be created")
    parser.add_argument("--issue", help="Optional issue key used for placeholder replacement")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files instead of skipping them")
    args = parser.parse_args()

    feature_slug = ensure_ascii_slug(args.feature)
    workspace = Path(args.workspace).resolve()
    results = bootstrap(workspace, feature_slug, args.issue, args.overwrite)

    print(f"feature-doc-bootstrap complete for `{feature_slug}`")
    for path, status in results:
        print(f"- [{status}] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
