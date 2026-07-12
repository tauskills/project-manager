#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "references" / "templates"

OPENAPI_STUB = """openapi: 3.1.0
info:
  title: {feature_slug}
  version: 0.1.0
paths: {{}}
"""

TEMPLATE_MAPPINGS = {
    "prd": ("prd-template.md", "docs/product/{feature_slug}.md"),
    "ui": ("ui-design-template.md", "docs/design/{feature_slug}.md"),
    "development": ("architecture-design-template.md", "docs/development/{feature_slug}.md"),
    "testing": ("test-case-template.md", "docs/testing/{feature_slug}-test-cases.md"),
    "test-report": ("test-report-template.md", "docs/testing/{feature_slug}-test-report.md"),
    "retrospective": ("retrospective-template.md", "docs/retrospective/{feature_slug}-retro.md"),
}

DIRECTORIES = [
    "docs/product",
    "docs/design",
    "docs/design/{feature_slug}",
    "docs/design/{feature_slug}/screens",
    "docs/design/{feature_slug}/assets",
    "docs/design/{feature_slug}/exports",
    "docs/development",
    "docs/development/openapi",
    "docs/development/schema",
    "docs/testing",
    "docs/retrospective",
    "docs/release",
    "docs/review/prd-qa",
    "docs/review/ui-design",
    "docs/review/test-case",
    "docs/review/architecture-design",
    "docs/review/artifact-consistency",
    "docs/review/feature-governance",
    "docs/review/release-readiness",
]

EXTRA_FILES = {
    "docs/design/{feature_slug}.fig": "",
    "docs/development/openapi/openapi.yaml": OPENAPI_STUB,
    "docs/development/schema/{feature_slug}.sql": "-- schema stub for {feature_slug}\n",
    "docs/project/project-status.yaml": (TEMPLATE_DIR / "project-status-template.yaml").read_text(encoding="utf-8"),
}


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

    for directory in DIRECTORIES:
        resolved = workspace / directory.format(feature_slug=feature_slug)
        resolved.mkdir(parents=True, exist_ok=True)
        results.append((str(resolved), "dir"))

    for _, (template_name, target_pattern) in TEMPLATE_MAPPINGS.items():
        target = workspace / target_pattern.format(feature_slug=feature_slug)
        template = render_template(load_reference_template(template_name), feature_slug, issue_key)
        status = write_if_missing(target, template, overwrite)
        results.append((str(target), status))

    for pattern, raw_content in EXTRA_FILES.items():
        target = workspace / pattern.format(feature_slug=feature_slug)
        content = render_template(raw_content, feature_slug, issue_key)
        # The OpenAPI file is project-wide state, not a feature-owned artifact.
        protected = {"docs/development/openapi/openapi.yaml", "docs/project/project-status.yaml"}
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
