#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

try:
    from .document_bundle import write_bundle
except ImportError:  # Support direct execution from the skill directory.
    from document_bundle import write_bundle


TEMPLATE = Path(__file__).resolve().parent.parent / "references/templates/release-record-template.md"
RELEASE_CHAPTERS = ["basic-info", "release-scope", "pre-release-gates", "configuration-differences", "dependencies", "release-steps", "rollback-steps", "monitoring", "smoke-check", "release-result", "retrospective"]


def normalize_segment(value: str, label: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9-]+", "-", value.strip()).strip("-").lower()
    if not normalized:
        raise ValueError(f"{label} must contain an ASCII letter or digit")
    return normalized


def bootstrap_release(workspace: Path, date: str, issue: str, slug: str) -> tuple[Path, str]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("date must use YYYY-MM-DD")
    raw_issue = issue.strip()
    if raw_issue.lower() == "no-issue":
        canonical_issue = "no-issue"
    elif re.fullmatch(r"[A-Za-z][A-Za-z0-9]+-\d+", raw_issue):
        canonical_issue = raw_issue.upper()
    else:
        raise ValueError("issue must use an uppercase key and number, for example TAU-123, or no-issue")
    slug_segment = normalize_segment(slug, "slug")
    target = workspace / f"docs/release/{date}-{canonical_issue}-{slug_segment}"
    legacy_target = target.with_suffix(".md")
    if legacy_target.exists():
        raise ValueError(f"legacy flat release record exists: {legacy_target}; migrate it to the numbered release bundle first")
    if target.exists():
        return target, "skipped"
    content = TEMPLATE.read_text(encoding="utf-8").replace("{date}", date).replace("{issue-key}", issue)
    write_bundle(target, content, RELEASE_CHAPTERS)
    return target, "written"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one event-scoped release record from the canonical template.")
    parser.add_argument("--workspace", default=".", help="Business repo root")
    parser.add_argument("--date", required=True, help="Release date in YYYY-MM-DD format")
    parser.add_argument("--issue", required=True, help="Issue or milestone identifier")
    parser.add_argument("--slug", required=True, help="Short release slug")
    args = parser.parse_args()
    target, status = bootstrap_release(Path(args.workspace).resolve(), args.date, args.issue, args.slug)
    print(f"release-record-bootstrap [{status}] {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
