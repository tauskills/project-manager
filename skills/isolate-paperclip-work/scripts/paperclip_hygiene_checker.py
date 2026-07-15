#!/usr/bin/env python3
import argparse
import json
import os
import re
from pathlib import Path, PurePosixPath

try:
    from .paperclip_session import (
        PROCESS_RELATIVE,
        SESSION_KEY_RE,
        contract_digest_is_valid,
        delivery_digest_is_valid,
        effective_changed_paths,
        git_command,
        git_status_entries,
        is_git_ignored,
        path_matches_contract,
        validate_contract_paths,
        validate_session_key_list,
        validate_verification_commands,
    )
except ImportError:  # Support direct execution from the skill directory.
    from paperclip_session import (
        PROCESS_RELATIVE,
        SESSION_KEY_RE,
        contract_digest_is_valid,
        delivery_digest_is_valid,
        effective_changed_paths,
        git_command,
        git_status_entries,
        is_git_ignored,
        path_matches_contract,
        validate_contract_paths,
        validate_session_key_list,
        validate_verification_commands,
    )


NOTE_RE = re.compile(r"^\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
SCREEN_RE = re.compile(
    r"^(\d{3})-(?:before|after|error|verification)-[a-z0-9]+(?:-[a-z0-9]+)*\.(?:png|jpe?g|webp)$"
)
TASK_PATH_RE = re.compile(
    r"(?:^|/)(?:paperclip[-_](?:task|agent|run|session|prompt|todo|handoff)[^/]*|task[-_](?:\d+|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}))(?:[./_-]|$)",
    re.IGNORECASE,
)
PAPERCLIP_CONTEXT_RE = re.compile(
    r"(?:paperclip.{0,48}\b(?:task|agent|prompt|assignment|run|session)\b|\b(?:task|agent|prompt|assignment|run|session)\b.{0,48}paperclip)",
    re.IGNORECASE,
)
PROCESS_LINK_RE = re.compile(r"(?:^|[/'\"`])\.run/paperclip(?:/|$)")
UNCHECKED_TODO_RE = re.compile(r"^\s*[-*]\s+\[\s\]", re.MULTILINE)
IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
)
IGNORED_WALK_DIRS = {
    ".git", ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "__pycache__", "build", "coverage", "dist", "node_modules", "target", "vendor", "venv",
}
REQUIRED_SESSION_FILES = {"context.json", "todo.md", "handoff.md", "evidence.md"}
OPTIONAL_SESSION_FILES = {"delivery.json"}
ALLOWED_SESSION_DIRS = {"notes", "screens", "logs", "scratch"}
ALLOWED_PROCESS_ROOT_DIRECTORIES = {"sessions", "checkouts"}
ALLOWED_PROCESS_ROOT_FILES = {".lifecycle.lock"}
FORBIDDEN_CONTEXT_KEYS = {
    "authorization", "cookie", "password", "prompt", "prompt_text", "secret", "task_name", "task_title", "token",
}
BROAD_ALLOW_PATHS = {".", "apps", "config", "docs", "packages", "scripts", "src", "test", "tests"}
TITLE_STOPWORDS = {
    "a", "add", "an", "and", "bug", "change", "create", "feature", "fix", "for", "implement",
    "improve", "in", "of", "optimize", "support", "task", "the", "to", "update", "with",
}
PATH_STOPWORDS = {
    "apps", "config", "doc", "docs", "md", "packages", "py", "script", "scripts", "spec", "src",
    "test", "tests", "ts", "tsx", "txt", "vue",
}
CHINESE_TASK_PREFIX_RE = re.compile(r"^(?:修复|新增|增加|实现|优化|支持|完成|处理|调整|更新)+")
CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".dart", ".go", ".java", ".js", ".jsx", ".kt", ".php",
    ".py", ".rb", ".rs", ".swift", ".ts", ".tsx", ".vue",
}


def finding(severity: str, code: str, path: str, message: str, repair: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "path": path, "message": message, "repair": repair}


def relative_path(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


def validate_allow_paths(values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        candidate = PurePosixPath(value.strip().strip("/"))
        rendered = candidate.as_posix()
        if not value or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"invalid allow path: {value}")
        if rendered in BROAD_ALLOW_PATHS or len(candidate.parts) < 2:
            raise ValueError(f"allow path is too broad: {value}")
        normalized.append(rendered)
    return normalized


def is_allowed(relative: str, allow_paths: list[str]) -> bool:
    return any(relative == root or relative.startswith(f"{root}/") for root in allow_paths)


def decode_names(output: bytes) -> list[str]:
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in output.split(b"\0")
        if item
    ]


def fallback_repository_names(workspace: Path) -> list[str]:
    names = []
    for root, dirs, files in os.walk(workspace):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if name not in IGNORED_WALK_DIRS]
        if root_path == workspace / PROCESS_RELATIVE or workspace / PROCESS_RELATIVE in root_path.parents:
            dirs[:] = []
            continue
        names.extend(relative_path(workspace, root_path / name) for name in files)
    return sorted(names)


def repository_names(workspace: Path, scan_mode: str, changed_paths: list[str]) -> list[str]:
    if scan_mode == "changed":
        return sorted(set(changed_paths))
    if scan_mode == "staged":
        result = git_command(workspace, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--")
        if result is not None and result.returncode == 0:
            return sorted(decode_names(result.stdout))
        return []
    result = git_command(workspace, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if result is not None and result.returncode == 0:
        return sorted(decode_names(result.stdout))
    return fallback_repository_names(workspace)


def read_bytes(workspace: Path, relative: str, scan_mode: str) -> bytes | None:
    if scan_mode == "staged":
        result = git_command(workspace, "show", f":{relative}")
        if result is not None and result.returncode == 0:
            return result.stdout
    path = workspace / relative
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def read_text(workspace: Path, relative: str, scan_mode: str, limit: int = 2_000_000) -> tuple[str | None, str | None]:
    raw = read_bytes(workspace, relative, scan_mode)
    if raw is None:
        return None, "unreadable"
    if len(raw) > limit:
        return None, "large"
    if b"\0" in raw:
        return None, "binary"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "binary"


def split_terms(value: str) -> list[str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", separated)]


def meaningful_title_terms(title: str) -> list[str]:
    return [term for term in split_terms(title) if term not in TITLE_STOPWORDS and len(term) > 1]


def compact_chinese(value: str) -> str:
    return "".join(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def title_derived(candidate: str, task_title: str | None) -> bool:
    if not task_title:
        return False
    title_terms = meaningful_title_terms(task_title)
    candidate_terms = [term for term in split_terms(candidate) if term not in TITLE_STOPWORDS | PATH_STOPWORDS]
    if len(title_terms) >= 2 and candidate_terms:
        title_set, candidate_set = set(title_terms), set(candidate_terms)
        coverage = len(title_set & candidate_set) / len(title_set)
        precision = len(title_set & candidate_set) / len(candidate_set)
        if coverage >= 0.8 and precision >= 0.6 and len(candidate_terms) <= len(title_terms) + 2:
            return True
    chinese_title = CHINESE_TASK_PREFIX_RE.sub("", compact_chinese(task_title))
    chinese_candidate = compact_chinese(candidate)
    return len(chinese_title) >= 4 and chinese_title in chinese_candidate


def normalize_reference(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def add_reference(references: dict[str, str], kind: str, value: object) -> None:
    if isinstance(value, str) and len(value.strip()) >= 4:
        references[value.strip()] = kind


def load_context(path: Path) -> dict:
    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return context if isinstance(context, dict) else {}


def validate_delivery(session: Path, context: dict, findings: list[dict[str, str]], workspace: Path) -> None:
    delivery_path = session / "delivery.json"
    relative = relative_path(workspace, delivery_path)
    try:
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        findings.append(finding("revise", "delivery.missing", relative, f"A valid delivery record is required at closure: {exc}", "Close the session with paperclip_session.py close."))
        return
    verification = delivery.get("verification", []) if isinstance(delivery, dict) else []
    commands = context.get("verification_commands", [])
    if not isinstance(delivery, dict) or not delivery_digest_is_valid(delivery):
        findings.append(finding("block", "delivery.digest", relative, "The delivery record digest does not match.", "Regenerate it with paperclip_session.py close."))
        return
    if len(verification) != len(commands) or any(
        not isinstance(item, dict)
        or item.get("status") != "passed"
        or item.get("command") != commands[index]
        for index, item in enumerate(verification)
    ):
        findings.append(finding("block", "delivery.verification", relative, "The delivery record does not prove that every verification command passed.", "Run every declared verification command successfully."))
    outputs = delivery.get("expected_outputs", []) if isinstance(delivery, dict) else []
    expected_paths = context.get("expected_outputs", [])
    if [item.get("path") for item in outputs if isinstance(item, dict)] != expected_paths or any(
        not isinstance(item, dict) or not item.get("exists") for item in outputs
    ):
        findings.append(finding("block", "delivery.outputs", relative, "One or more expected project outputs are missing.", "Create and verify every expected output."))


def check_scope(
    workspace: Path,
    session: Path,
    context: dict,
    phase: str,
    findings: list[dict[str, str]],
    passes: list[str],
) -> list[str]:
    relative = relative_path(workspace, session / "context.json")
    if context.get("schema_version") != 2:
        findings.append(finding("block" if phase == "close" else "revise", "context.schema", relative, "The session does not use the version 2 scope contract.", "Create a new session with the current paperclip_session.py."))
        return []
    if not contract_digest_is_valid(context):
        findings.append(finding("block", "scope.contract_tampered", relative, "The immutable session contract digest does not match.", "Abandon this session or restore the original contract; create a new session to change scope."))
        return []
    allowed = context.get("allowed_paths")
    forbidden = context.get("forbidden_paths", [])
    commands = context.get("verification_commands")
    baseline = context.get("baseline_changes")
    if not isinstance(allowed, list) or not allowed:
        findings.append(finding("block", "scope.allowed_missing", relative, "The session has no allowed_paths contract.", "Declare the smallest project paths this session may change."))
        return []
    if not isinstance(forbidden, list) or not isinstance(commands, list) or not commands:
        findings.append(finding("block", "scope.contract_invalid", relative, "The path or verification contract is incomplete.", "Recreate the session with explicit paths and verification commands."))
        return []
    try:
        allowed = validate_contract_paths(allowed, "allowed path")
        forbidden = validate_contract_paths(forbidden, "forbidden path")
        validate_verification_commands(commands)
        validate_contract_paths(context.get("expected_outputs", []), "expected output", allow_globs=False)
        if "overlapping_session_keys" not in context:
            raise ValueError("session context does not record overlapping_session_keys")
        validate_session_key_list(context["overlapping_session_keys"])
    except (AttributeError, TypeError, ValueError) as exc:
        findings.append(finding("block", "scope.contract_invalid", relative, str(exc), "Create a new session with a valid minimal contract."))
        return []
    if not isinstance(context.get("baseline_head"), str) or not isinstance(baseline, dict):
        findings.append(finding("block", "scope.baseline_missing", relative, "The session has no valid Git baseline.", "Recreate the session before modifying project files."))
        return []
    try:
        changed = effective_changed_paths(workspace, context, session.name)
    except ValueError as exc:
        findings.append(finding("block", "scope.git_error", relative, str(exc), "Restore the repository baseline or recreate the session."))
        return []
    for path in changed:
        if path_matches_contract(path, forbidden):
            findings.append(finding("block", "scope.forbidden", path, "The agent changed a path explicitly forbidden by the session contract.", "Revert the change or obtain a new, explicit scope contract."))
        elif not path_matches_contract(path, allowed):
            findings.append(finding("block", "scope.outside", path, "The agent changed a path outside allowed_paths.", "Revert the change or create a new session with a justified minimal scope."))
    if not any(item["code"].startswith("scope.") for item in findings):
        passes.append(f"Git changes stay within the session scope: {len(changed)} path(s)")
    return changed


def check_process_area(
    workspace: Path,
    phase: str,
    selected_session: str | None,
    findings: list[dict[str, str]],
    passes: list[str],
) -> tuple[dict[str, str], dict[str, dict], list[str]]:
    process_root = workspace / PROCESS_RELATIVE
    references: dict[str, str] = {}
    contexts: dict[str, dict] = {}
    changed_paths: list[str] = []
    if not process_root.exists():
        if selected_session:
            findings.append(finding("block", "session.selected_missing", selected_session, "The selected session does not exist.", "Pass an existing session key."))
        else:
            passes.append("No local Paperclip process area is present")
        return references, contexts, changed_paths
    if process_root.is_symlink():
        findings.append(finding("block", "process.symlink", PROCESS_RELATIVE.as_posix(), "The process root is a symlink.", "Replace it with a local directory."))
        return references, contexts, changed_paths
    if not is_git_ignored(workspace):
        findings.append(finding("block", "process.not_ignored", PROCESS_RELATIVE.as_posix(), "The process area is not ignored by Git.", "Add `/.run/paperclip/` to .gitignore."))
    else:
        passes.append("The process area is ignored by Git")

    tracked = git_command(workspace, "ls-files", "-z", "--", PROCESS_RELATIVE.as_posix())
    if tracked is not None and tracked.returncode == 0:
        for path in decode_names(tracked.stdout):
            findings.append(finding("block", "process.tracked", path, "A Paperclip process artifact is tracked by Git.", "Remove it from the index and keep the ignore rule."))
    sessions_root = process_root / "sessions"
    checkouts_root = process_root / "checkouts"
    for child in sorted(process_root.iterdir()):
        allowed_directory = child.name in ALLOWED_PROCESS_ROOT_DIRECTORIES and child.is_dir() and not child.is_symlink()
        allowed_file = child.name in ALLOWED_PROCESS_ROOT_FILES and child.is_file() and not child.is_symlink()
        if not allowed_directory and not allowed_file:
            findings.append(finding("revise", "process.root_entry", relative_path(workspace, child), "Only the sessions and runtime checkouts directories are allowed at the process root.", "Move the artifact into the active session or delete it."))
    if checkouts_root.exists() and (checkouts_root.is_symlink() or not checkouts_root.is_dir()):
        findings.append(finding("block", "process.checkouts_invalid", relative_path(workspace, checkouts_root), "The runtime checkouts path must be a local directory.", "Remove the invalid path and let the execution harness recreate the checkout directory."))
    if sessions_root.is_symlink():
        findings.append(finding("block", "process.sessions_symlink", relative_path(workspace, sessions_root), "The sessions directory is a symlink.", "Replace it with a local directory."))
        return references, contexts, changed_paths
    if not sessions_root.is_dir():
        findings.append(finding("revise", "process.sessions_missing", relative_path(workspace, process_root), "The sessions directory is missing.", "Create process sessions with paperclip_session.py."))
        return references, contexts, changed_paths

    session_paths = sorted(sessions_root.iterdir())
    selected_path = sessions_root / selected_session if selected_session else None
    if selected_path is not None and not selected_path.is_dir():
        findings.append(finding("block", "session.selected_missing", f"{PROCESS_RELATIVE.as_posix()}/sessions/{selected_session}", "The selected session does not exist.", "Pass an existing session key."))
    if selected_path is not None and selected_path.is_dir():
        session_paths = [selected_path]
    for session in session_paths:
        session_rel = relative_path(workspace, session)
        if session.is_symlink():
            findings.append(finding("block", "session.symlink", session_rel, "Process sessions must not be symlinks.", "Create a local session directory."))
            continue
        if not session.is_dir():
            findings.append(finding("revise", "session.unexpected_file", session_rel, "A file exists directly under sessions.", "Move it into a valid session or delete it."))
            continue
        if not SESSION_KEY_RE.fullmatch(session.name):
            findings.append(finding("revise", "session.naming", session_rel, "The session key is not a UTC timestamp plus a domain slug.", "Create a new session with paperclip_session.py."))

        direct = {path.name: path for path in session.iterdir()}
        for name in sorted(REQUIRED_SESSION_FILES - direct.keys()):
            findings.append(finding("revise", "session.required_file", f"{session_rel}/{name}", "A required process file is missing.", "Restore the fixed session file."))
        for name in sorted(ALLOWED_SESSION_DIRS - direct.keys()):
            findings.append(finding("revise", "session.required_directory", f"{session_rel}/{name}", "A required process directory is missing.", "Restore the fixed session directory."))
        for name, path in sorted(direct.items()):
            if name not in REQUIRED_SESSION_FILES | OPTIONAL_SESSION_FILES | ALLOWED_SESSION_DIRS:
                findings.append(finding("revise", "session.unexpected_entry", relative_path(workspace, path), "The artifact is outside the fixed session layout.", "Move it into notes, screens, logs, or scratch."))
        for path in session.rglob("*"):
            if path.is_symlink():
                findings.append(finding("block", "process.nested_symlink", relative_path(workspace, path), "Process artifacts must not be symlinks.", "Replace the link with a local, non-sensitive artifact."))

        context_path = session / "context.json"
        context = load_context(context_path) if context_path.is_file() else {}
        contexts[session.name] = context
        forbidden = FORBIDDEN_CONTEXT_KEYS.intersection(context)
        if forbidden:
            findings.append(finding("block", "context.forbidden_fields", relative_path(workspace, context_path), f"Forbidden context fields: {', '.join(sorted(forbidden))}.", "Remove titles, prompts, and secret-bearing fields; keep only opaque references."))
        if context.get("tool") != "paperclip":
            findings.append(finding("revise", "context.tool", relative_path(workspace, context_path), "The context tool marker is invalid.", "Recreate the session with paperclip_session.py."))
        if context.get("session_key") != session.name:
            findings.append(finding("revise", "context.session_key", relative_path(workspace, context_path), "session_key does not match the directory.", "Use the directory session key in context.json."))
        if context.get("retention") not in {"discard", "external-archive"}:
            findings.append(finding("revise", "context.retention", relative_path(workspace, context_path), "retention must be discard or external-archive.", "Set an explicit supported retention policy."))
        add_reference(references, "task_ref", context.get("task_ref"))
        add_reference(references, "agent_ref", context.get("agent_ref"))

        inspect_phase = session.name == selected_session if selected_session else len(session_paths) == 1
        if inspect_phase:
            changed_paths.extend(check_scope(workspace, session, context, phase, findings, passes))
        todo_path = session / "todo.md"
        if phase == "close" and inspect_phase and todo_path.is_file():
            todo_text = todo_path.read_text(encoding="utf-8", errors="replace")
            if UNCHECKED_TODO_RE.search(todo_text):
                findings.append(finding("revise", "todo.open", relative_path(workspace, todo_path), "The session still has unfinished TODO items.", "Complete or explicitly cancel every item before closure."))
            validate_delivery(session, context, findings, workspace)

        notes = session / "notes"
        if notes.is_dir():
            for note in sorted(path for path in notes.iterdir() if path.is_file()):
                if not NOTE_RE.fullmatch(note.name):
                    findings.append(finding("revise", "notes.naming", relative_path(workspace, note), "Note names must use a three-digit sequence and topic slug.", "Rename it to NNN-topic-slug.md."))
        screens = session / "screens"
        screen_files = sorted(path for path in screens.iterdir() if path.is_file()) if screens.is_dir() else []
        sequence = []
        evidence_text = (session / "evidence.md").read_text(encoding="utf-8", errors="replace") if (session / "evidence.md").is_file() else ""
        for screen in screen_files:
            match = SCREEN_RE.fullmatch(screen.name)
            if not match:
                findings.append(finding("revise", "screens.naming", relative_path(workspace, screen), "Screenshot naming does not identify sequence, evidence type, and surface.", "Use NNN-{before|after|error|verification}-{surface}.ext."))
                continue
            sequence.append(int(match.group(1)))
            if screen.name not in evidence_text:
                findings.append(finding("revise", "screens.unindexed", relative_path(workspace, screen), "The screenshot is absent from evidence.md.", "Add its purpose, UTC capture time, and redaction status to the evidence index."))
        if sequence and sequence != list(range(1, len(sequence) + 1)):
            findings.append(finding("revise", "screens.sequence", relative_path(workspace, screens), "Screenshot sequence numbers are not continuous from 001.", "Renumber screenshots and update evidence.md."))
        for path in sorted(item for item in session.rglob("*") if item.is_file()):
            try:
                raw = path.read_bytes()
            except OSError as exc:
                findings.append(finding("revise", "process.unreadable", relative_path(workspace, path), str(exc), "Restore readable local evidence or delete it."))
                continue
            if len(raw) > 10_000_000:
                findings.append(finding("revise", "process.too_large", relative_path(workspace, path), "The process artifact exceeds 10 MB.", "Trim logs or move approved evidence to the external archive."))
                continue
            if b"\0" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                findings.append(finding("block", "process.secret", relative_path(workspace, path), "A high-confidence credential pattern exists in a process artifact.", "Remove and rotate the credential; retain only redacted evidence."))

    if not selected_session and len(session_paths) > 1:
        findings.append(finding("revise", "scope.session_required", PROCESS_RELATIVE.as_posix(), "Multiple sessions exist, so changes cannot be attributed safely.", "Pass --session for the current agent session."))
    if not any(item["code"].startswith(("process.", "session.", "context.", "todo.", "notes.", "screens.")) for item in findings):
        passes.append("Paperclip process sessions follow the isolated layout")
    return references, contexts, sorted(set(changed_paths))


def check_project_assets(
    workspace: Path,
    references: dict[str, str],
    task_title: str | None,
    allow_paths: list[str],
    scan_mode: str,
    changed_paths: list[str],
    findings: list[dict[str, str]],
    passes: list[str],
) -> None:
    leaks = 0
    process = PROCESS_RELATIVE.as_posix()
    for relative in repository_names(workspace, scan_mode, changed_paths):
        if relative == process or relative.startswith(f"{process}/"):
            continue
        allowed = is_allowed(relative, allow_paths)
        if TASK_PATH_RE.search(relative) and not allowed:
            findings.append(finding("revise", "naming.task_shaped", relative, "The path is named like execution-specific task or Paperclip material.", "Rename it after a stable domain capability and manually confirm it is not task-title-derived."))
            leaks += 1
        if title_derived(relative, task_title):
            findings.append(finding("revise", "naming.task_title_path", relative, "The path closely matches the runtime task title.", "Choose a stable project-domain name and confirm it was not mechanically derived from the task title."))
            leaks += 1

        normalized_relative = normalize_reference(relative)
        for ref, kind in references.items():
            normalized_ref = normalize_reference(ref)
            if len(normalized_ref) >= 4 and normalized_ref in normalized_relative:
                findings.append(finding("block", f"leak.{kind}.path", relative, f"The path contains the current {kind}.", "Rename it after the owned domain concept."))
                leaks += 1

        text, reason = read_text(workspace, relative, scan_mode)
        if reason == "large":
            findings.append(finding("revise", "scan.too_large", relative, "The text file exceeds the automatic scan limit.", "Inspect it manually for Paperclip execution context."))
            continue
        if text is None:
            continue
        for ref, kind in references.items():
            if ref in text:
                findings.append(finding("block", f"leak.{kind}.content", relative, f"The file contains the current {kind}.", "Remove the execution reference and retain only a project-owned reference if required."))
                leaks += 1
        if relative != ".gitignore" and PROCESS_LINK_RE.search(text) and not allowed:
            findings.append(finding("block", "leak.process_dependency", relative, "A project asset refers to the local Paperclip process area.", "Remove the link or dependency and cite project-owned evidence."))
            leaks += 1
        if relative != ".gitignore" and PAPERCLIP_CONTEXT_RE.search(text) and not allowed:
            findings.append(finding("block", "leak.paperclip_context", relative, "The file contains Paperclip execution-context language.", "Remove task/agent/run provenance or scope a verified product integration with --allow-path."))
            leaks += 1
        if task_title and Path(relative).suffix.lower() in CODE_SUFFIXES:
            symbol = next((match.group(0) for match in IDENTIFIER_RE.finditer(text) if title_derived(match.group(0), task_title)), None)
            if symbol:
                findings.append(finding("revise", "naming.task_title_identifier", relative, "A code identifier closely matches the runtime task title.", "Rename it for a stable domain responsibility and review similar identifiers."))
                leaks += 1
    if not leaks:
        passes.append(f"No explicit Paperclip execution context was found in {scan_mode} project assets")


def check_git_provenance(
    workspace: Path,
    context: dict | None,
    references: dict[str, str],
    task_title: str | None,
    findings: list[dict[str, str]],
    passes: list[str],
) -> None:
    branch_result = git_command(workspace, "branch", "--show-current")
    branch = branch_result.stdout.decode("utf-8", errors="replace").strip() if branch_result and branch_result.returncode == 0 else ""
    if branch:
        normalized_branch = normalize_reference(branch)
        for ref, kind in references.items():
            normalized_ref = normalize_reference(ref)
            if len(normalized_ref) >= 4 and normalized_ref in normalized_branch:
                findings.append(finding("block", f"git.{kind}.branch", branch, f"The branch name contains the current {kind}.", "Rename the branch after a stable project-domain change."))
        if title_derived(branch, task_title):
            findings.append(finding("revise", "git.task_title.branch", branch, "The branch name closely matches the runtime task title.", "Use a stable domain-oriented branch name."))
    baseline_head = context.get("baseline_head") if context else None
    if not isinstance(baseline_head, str):
        return
    log_result = git_command(workspace, "log", "--format=%s%x00", f"{baseline_head}..HEAD")
    if log_result is None or log_result.returncode != 0:
        return
    for subject in decode_names(log_result.stdout):
        for ref, kind in references.items():
            if ref in subject:
                findings.append(finding("block", f"git.{kind}.commit", "git-log", f"A session commit subject contains the current {kind}.", "Rewrite the commit message with project-owned terminology."))
        if PAPERCLIP_CONTEXT_RE.search(subject):
            findings.append(finding("block", "git.paperclip_context.commit", "git-log", "A session commit subject contains Paperclip execution context.", "Rewrite the commit message with project-owned terminology."))
        if title_derived(subject, task_title):
            findings.append(finding("revise", "git.task_title.commit", "git-log", "A session commit subject closely matches the runtime task title.", "Rewrite it as a stable description of the project change."))
    if not any(item["code"].startswith("git.") for item in findings):
        passes.append("Branch and session commit subjects are free of detected Paperclip coupling")


def analyze(
    workspace: Path,
    phase: str = "work",
    selected_session: str | None = None,
    allow_paths: list[str] | None = None,
    task_title: str | None = None,
    task_ref: str | None = None,
    agent_ref: str | None = None,
    scan_mode: str = "repository",
) -> dict:
    workspace = workspace.resolve()
    findings: list[dict[str, str]] = []
    passes: list[str] = []
    changed_paths: list[str] = []
    if scan_mode not in {"repository", "changed", "staged"}:
        raise ValueError(f"unsupported scan mode: {scan_mode}")
    if not workspace.is_dir():
        findings.append(finding("block", "workspace.missing", str(workspace), "The workspace is not a directory.", "Pass an existing project repository."))
    else:
        allowed = validate_allow_paths(allow_paths or [])
        references, contexts, changed_paths = check_process_area(
            workspace, phase, selected_session, findings, passes
        )
        add_reference(references, "task_ref", task_ref)
        add_reference(references, "agent_ref", agent_ref)
        selected_context = contexts.get(selected_session) if selected_session else (
            next(iter(contexts.values())) if len(contexts) == 1 else None
        )
        if scan_mode == "changed" and not changed_paths and selected_context is None:
            try:
                changed_paths = sorted(git_status_entries(workspace))
            except ValueError:
                changed_paths = fallback_repository_names(workspace)
        check_project_assets(
            workspace,
            references,
            task_title,
            allowed,
            scan_mode,
            changed_paths,
            findings,
            passes,
        )
        check_git_provenance(workspace, selected_context, references, task_title, findings, passes)
    decision = "block" if any(item["severity"] == "block" for item in findings) else "revise" if findings else "allow"
    return {
        "decision": decision,
        "risk": {"allow": "low", "revise": "medium", "block": "high"}[decision],
        "phase": phase,
        "scan_mode": scan_mode,
        "changed_paths": changed_paths,
        "passes": passes,
        "findings": findings,
        "manual_checks": [
            "Confirm that durable names describe stable domain concepts rather than a task title, even when similarity detection passes.",
            "Confirm that promoted documentation states project facts and cites a canonical project source, not Paperclip execution narration.",
        ],
    }


def render_text(result: dict) -> str:
    lines = [
        "# Paperclip Hygiene Report",
        "",
        f"- Decision: `{result['decision']}`",
        f"- Risk: `{result['risk']}`",
        f"- Phase: `{result['phase']}`",
        f"- Scan: `{result['scan_mode']}`",
        "",
        "## Findings",
        "",
    ]
    if result["findings"]:
        lines.extend(
            f"- `{item['severity']}` `{item['code']}` `{item['path']}`: {item['message']} {item['repair']}"
            for item in result["findings"]
        )
    else:
        lines.append("No automated findings.")
    lines.extend(["", "## Manual Checks", ""])
    lines.extend(f"- {item}" for item in result["manual_checks"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Paperclip scope, process isolation, and task-context leakage.")
    parser.add_argument("--workspace", required=True, help="Target project repository")
    parser.add_argument("--phase", choices=["work", "close"], default="work")
    parser.add_argument("--session", help="Current session key; required to attribute multiple active agents safely")
    parser.add_argument("--scan", choices=["repository", "changed", "staged"], default="changed")
    parser.add_argument("--task-title", help="Runtime-only task title; prefer PAPERCLIP_TASK_TITLE")
    parser.add_argument("--task-ref", help="Runtime-only task reference; prefer PAPERCLIP_TASK_REF")
    parser.add_argument("--agent-ref", help="Runtime-only agent reference; prefer PAPERCLIP_AGENT_REF")
    parser.add_argument("--allow-path", action="append", default=[], help="Narrow product-owned Paperclip integration path; repeatable")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--fail-on", choices=["revise", "block"], help="Return 1 when the decision reaches this threshold")
    args = parser.parse_args()
    try:
        result = analyze(
            Path(args.workspace),
            args.phase,
            args.session,
            args.allow_path,
            task_title=args.task_title or os.getenv("PAPERCLIP_TASK_TITLE"),
            task_ref=args.task_ref or os.getenv("PAPERCLIP_TASK_REF"),
            agent_ref=args.agent_ref or os.getenv("PAPERCLIP_AGENT_REF"),
            scan_mode=args.scan,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render_text(result), end="")
    threshold = {"allow": 0, "revise": 1, "block": 2}
    return 1 if args.fail_on and threshold[result["decision"]] >= threshold[args.fail_on] else 0


if __name__ == "__main__":
    raise SystemExit(main())
