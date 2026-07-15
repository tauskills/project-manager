#!/usr/bin/env python3
import re
from pathlib import Path


NUMBERED_MARKDOWN_RE = re.compile(r"^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
SECTION_RE = re.compile(r"^##\s+.+?\s*$", re.MULTILINE)


def numbered_markdown_files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    markdown = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".md")
    invalid = [item.name for item in markdown if not NUMBERED_MARKDOWN_RE.fullmatch(item.name)]
    if invalid:
        raise ValueError(f"文档包包含非三位编号文件：{', '.join(invalid)}")
    if not markdown:
        raise ValueError(f"文档包没有三位编号 Markdown 文件：{path}")
    if markdown[0].name != "001-overview.md":
        raise ValueError(f"文档包必须以 001-overview.md 开始：{path}")
    numbers = [int(NUMBERED_MARKDOWN_RE.fullmatch(item.name).group(1)) for item in markdown]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"文档包章节编号不连续：{path}")
    return markdown


def read_document(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "\n\n".join(item.read_text(encoding="utf-8").strip() for item in numbered_markdown_files(path)) + "\n"


def document_slug(path: Path) -> str:
    if not path.is_dir():
        return path.stem
    if path.name in {"test-cases", "test-report"}:
        return f"{path.parent.name}-{path.name}"
    return path.name


def split_template(template: str, chapter_slugs: list[str]) -> list[tuple[str, str]]:
    matches = list(SECTION_RE.finditer(template))
    if len(matches) != len(chapter_slugs):
        raise ValueError(f"模板章节数 {len(matches)} 与文件名定义数 {len(chapter_slugs)} 不一致。")
    chunks = [("overview", template[:matches[0].start()].strip() + "\n")]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(template)
        chunks.append((chapter_slugs[index], template[match.start():end].strip() + "\n"))
    files = [(f"{index:03d}-{slug}.md", content) for index, (slug, content) in enumerate(chunks, 1)]
    catalog = ["", "## 章节目录", ""] + [f"- [{filename}]({filename})" for filename, _ in files[1:]]
    files[0] = (files[0][0], files[0][1].rstrip() + "\n" + "\n".join(catalog) + "\n")
    return files


def write_bundle(path: Path, template: str, chapter_slugs: list[str], overwrite: bool = False) -> list[tuple[str, str]]:
    results = []
    for filename, content in split_template(template, chapter_slugs):
        target = path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            results.append((str(target), "skipped"))
            continue
        target.write_text(content, encoding="utf-8")
        results.append((str(target), "written"))
    return results
