#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parent.parent / "references/templates/release-record-template.md"


def normalize_segment(value: str, label: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9-]+", "-", value.strip()).strip("-").lower()
    if not normalized:
        raise ValueError(f"{label} must contain an ASCII letter or digit")
    return normalized


def bootstrap_release(workspace: Path, date: str, issue: str, slug: str) -> tuple[Path, str]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("date must use YYYY-MM-DD")
    issue_segment = normalize_segment(issue, "issue")
    slug_segment = normalize_segment(slug, "slug")
    target = workspace / f"docs/release/{date}-{issue_segment}-{slug_segment}.md"
    if target.exists():
        return target, "skipped"
    content = TEMPLATE.read_text(encoding="utf-8").replace("{date}", date).replace("{issue-key}", issue)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
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
