#!/usr/bin/env python3
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SESSION_KEY_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9]+(?:-[a-z0-9]+)*$")
PROHIBITED_SLUG_PARTS = {"agent", "paperclip", "session", "task", "temp", "temporary", "todo", "wip"}
PROCESS_RELATIVE = Path(".run/paperclip")
SESSION_DIRECTORIES = ("notes", "screens", "logs", "scratch")
BROAD_CONTRACT_PATHS = {".", "*", "**", "./**"}
CONTRACT_FIELDS = (
    "schema_version", "tool", "session_key", "domain_slug", "started_at", "status", "closed_at", "retention",
    "allowed_paths", "forbidden_paths", "expected_outputs", "verification_commands",
    "baseline_head", "baseline_changes", "managed_gitignore_fingerprint", "task_ref", "agent_ref",
)


def validate_slug(slug: str) -> None:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("slug must use lowercase kebab-case")
    prohibited = PROHIBITED_SLUG_PARTS.intersection(slug.split("-"))
    if prohibited:
        raise ValueError(f"slug contains process-oriented terms: {', '.join(sorted(prohibited))}")


def normalize_contract_path(value: str, field: str, allow_globs: bool = True) -> str:
    candidate = value.strip().replace("\\", "/")
    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or ".." in path.parts or candidate in BROAD_CONTRACT_PATHS:
        raise ValueError(f"invalid {field}: {value}")
    if not allow_globs and any(char in candidate for char in "*?["):
        raise ValueError(f"{field} must be a concrete path: {value}")
    rendered = path.as_posix().removeprefix("./").rstrip("/")
    if rendered == ".git" or rendered.startswith(".git/"):
        raise ValueError(f"{field} must not target Git internals: {value}")
    process = PROCESS_RELATIVE.as_posix()
    if rendered == process or rendered.startswith(f"{process}/"):
        raise ValueError(f"{field} must not target the Paperclip process area: {value}")
    return rendered


def validate_contract_paths(values: list[str], field: str, allow_globs: bool = True) -> list[str]:
    normalized = [normalize_contract_path(value, field, allow_globs) for value in values]
    return list(dict.fromkeys(normalized))


def path_matches_contract(relative: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if any(char in pattern for char in "*?["):
            if fnmatch.fnmatchcase(relative, pattern):
                return True
            if pattern.endswith("/**") and relative == pattern[:-3].rstrip("/"):
                return True
        elif relative == pattern or relative.startswith(f"{pattern}/"):
            return True
    return False


def validate_verification_commands(commands: list[list[str]]) -> list[list[str]]:
    normalized = []
    for command in commands:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("verification commands must be non-empty argument arrays")
        normalized.append(command)
    if not normalized:
        raise ValueError("at least one verification command is required")
    return normalized


def contract_digest(context: dict) -> str:
    payload = {key: context[key] for key in CONTRACT_FIELDS if key in context}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def contract_digest_is_valid(context: dict) -> bool:
    expected = context.get("contract_digest")
    return isinstance(expected, str) and expected == contract_digest(context)


def delivery_digest(delivery: dict) -> str:
    payload = {key: value for key, value in delivery.items() if key != "delivery_digest"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def delivery_digest_is_valid(delivery: dict) -> bool:
    expected = delivery.get("delivery_digest")
    return isinstance(expected, str) and expected == delivery_digest(delivery)


def write_delivery(path: Path, delivery: dict) -> None:
    delivery["delivery_digest"] = delivery_digest(delivery)
    path.write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_verification_command(value: str) -> list[str]:
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid verification command: {exc}") from exc
    if not command:
        raise argparse.ArgumentTypeError("verification command must not be empty")
    return command


def git_command(workspace: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    if not (workspace / ".git").exists():
        return None
    try:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None


def require_git_head(workspace: Path) -> str:
    result = git_command(workspace, "rev-parse", "--verify", "HEAD")
    if result is None or result.returncode != 0:
        raise ValueError("workspace must be a Git repository with an initial commit")
    return result.stdout.decode("ascii", errors="strict").strip()


def is_git_ignored(workspace: Path, relative: str = ".run/paperclip/.hygiene-probe") -> bool:
    result = git_command(workspace, "check-ignore", "--no-index", "--quiet", "--", relative)
    if result is not None:
        return result.returncode == 0
    gitignore = workspace / ".gitignore"
    if not gitignore.is_file():
        return False
    ignored = False
    for raw_line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line.removeprefix("!").lstrip("/")
        matches = relative.startswith(pattern) if pattern.endswith("/") else fnmatch.fnmatch(relative, pattern)
        if matches:
            ignored = not negated
    return ignored


def ensure_gitignore(workspace: Path) -> None:
    if is_git_ignored(workspace):
        return
    gitignore = workspace / ".gitignore"
    if gitignore.is_symlink():
        raise ValueError("refusing to update a symlinked .gitignore")
    current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    separator = "" if not current or current.endswith("\n") else "\n"
    addition = "# Paperclip local execution workspace\n/.run/paperclip/\n"
    gitignore.write_text(f"{current}{separator}{addition}", encoding="utf-8")


def assert_local_process_path(workspace: Path) -> None:
    current = workspace
    for part in PROCESS_RELATIVE.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"process path must not contain symlinks: {current}")


def normalize_time(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0)


def git_status_entries(workspace: Path) -> dict[str, str]:
    result = git_command(workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result is None or result.returncode != 0:
        raise ValueError("unable to read Git worktree status")
    entries: dict[str, str] = {}
    parts = result.stdout.split(b"\0")
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        text = raw.decode("utf-8", errors="surrogateescape")
        status, relative = text[:2], text[3:]
        entries[relative] = status
        if status[0] in {"R", "C"} and index < len(parts) and parts[index]:
            original = parts[index].decode("utf-8", errors="surrogateescape")
            entries[original] = status
            index += 1
    return entries


def fingerprint_workspace_path(workspace: Path, relative: str) -> str:
    path = workspace / relative
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}"
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "non-file"
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def capture_dirty_baseline(workspace: Path) -> dict[str, dict[str, str]]:
    process = PROCESS_RELATIVE.as_posix()
    return {
        relative: {"status": status, "fingerprint": fingerprint_workspace_path(workspace, relative)}
        for relative, status in git_status_entries(workspace).items()
        if relative != process and not relative.startswith(f"{process}/")
    }


def committed_paths_since(workspace: Path, baseline_head: str) -> set[str]:
    revisions = git_command(workspace, "rev-list", "--reverse", f"{baseline_head}..HEAD")
    if revisions is None or revisions.returncode != 0:
        raise ValueError("unable to compare the current HEAD with the session baseline")
    paths: set[str] = set()
    for revision in revisions.stdout.decode("ascii", errors="strict").splitlines():
        result = git_command(
            workspace,
            "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-m", "-z", revision,
        )
        if result is None or result.returncode != 0:
            raise ValueError(f"unable to inspect session commit {revision[:12]}")
        paths.update(
            item.decode("utf-8", errors="surrogateescape")
            for item in result.stdout.split(b"\0")
            if item
        )
    return paths


def peer_session_claims_path(
    workspace: Path,
    selected_session_key: str,
    relative: str,
) -> bool:
    sessions_root = workspace / PROCESS_RELATIVE / "sessions"
    if not sessions_root.is_dir() or sessions_root.is_symlink():
        return False
    for session in sessions_root.iterdir():
        if session.name == selected_session_key or not session.is_dir() or session.is_symlink():
            continue
        try:
            context = json.loads((session / "context.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            not isinstance(context, dict)
            or context.get("schema_version") != 2
            or context.get("status") not in {"active", "closed"}
            or not contract_digest_is_valid(context)
        ):
            continue
        try:
            allowed = validate_contract_paths(context.get("allowed_paths", []), "allowed path")
            forbidden = validate_contract_paths(context.get("forbidden_paths", []), "forbidden path")
        except (AttributeError, TypeError, ValueError):
            continue
        if not path_matches_contract(relative, allowed) or path_matches_contract(relative, forbidden):
            continue
        if context.get("status") == "active":
            return True
        try:
            delivery = json.loads((session / "delivery.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fingerprints = delivery.get("owned_path_fingerprints", {}) if isinstance(delivery, dict) else {}
        if (
            delivery_digest_is_valid(delivery)
            and delivery.get("status") == "closed"
            and delivery.get("hygiene_decision") == "allow"
            and isinstance(fingerprints, dict)
            and fingerprints.get(relative) == fingerprint_workspace_path(workspace, relative)
        ):
            return True
    return False


def effective_changed_paths(
    workspace: Path,
    context: dict,
    selected_session_key: str | None = None,
) -> list[str]:
    baseline_head = context.get("baseline_head")
    baseline = context.get("baseline_changes", {})
    if not isinstance(baseline_head, str) or not isinstance(baseline, dict):
        raise ValueError("session context does not contain a valid Git baseline")
    current_status = git_status_entries(workspace)
    effective = committed_paths_since(workspace, baseline_head)
    for relative in set(current_status) | set(baseline):
        current = {
            "status": current_status.get(relative, "  "),
            "fingerprint": fingerprint_workspace_path(workspace, relative),
        }
        if relative not in baseline or current != baseline[relative]:
            effective.add(relative)
    managed_gitignore = context.get("managed_gitignore_fingerprint")
    if managed_gitignore and fingerprint_workspace_path(workspace, ".gitignore") == managed_gitignore:
        effective.discard(".gitignore")
    process = PROCESS_RELATIVE.as_posix()
    changed = sorted(
        relative for relative in effective
        if relative != process and not relative.startswith(f"{process}/")
    )
    if not selected_session_key:
        return changed
    allowed = validate_contract_paths(context.get("allowed_paths", []), "allowed path")
    forbidden = validate_contract_paths(context.get("forbidden_paths", []), "forbidden path")
    return [
        relative for relative in changed
        if (
            path_matches_contract(relative, allowed)
            and not path_matches_contract(relative, forbidden)
        )
        or not peer_session_claims_path(workspace, selected_session_key, relative)
    ]


def active_peer_sessions(workspace: Path, selected_session_key: str) -> list[Path]:
    sessions_root = workspace / PROCESS_RELATIVE / "sessions"
    peers = []
    if not sessions_root.is_dir() or sessions_root.is_symlink():
        return peers
    for session in sessions_root.iterdir():
        if session.name == selected_session_key or not session.is_dir() or session.is_symlink():
            continue
        try:
            context = json.loads((session / "context.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(context, dict)
            and context.get("schema_version") == 2
            and context.get("status") == "active"
            and contract_digest_is_valid(context)
        ):
            peers.append(session)
    return peers


def purge_closed_discard_sessions(workspace: Path) -> None:
    sessions_root = workspace / PROCESS_RELATIVE / "sessions"
    if not sessions_root.is_dir() or sessions_root.is_symlink():
        return
    for session in list(sessions_root.iterdir()):
        if not session.is_dir() or session.is_symlink():
            continue
        try:
            context = json.loads((session / "context.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            delivery = json.loads((session / "delivery.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(context, dict)
            and context.get("schema_version") == 2
            and context.get("status") == "closed"
            and context.get("retention") == "discard"
            and contract_digest_is_valid(context)
            and isinstance(delivery, dict)
            and delivery_digest_is_valid(delivery)
            and delivery.get("status") == "closed"
            and delivery.get("hygiene_decision") == "allow"
        ):
            shutil.rmtree(session)


def create_session(
    workspace: Path,
    slug: str,
    allowed_paths: list[str],
    verification_commands: list[list[str]],
    forbidden_paths: list[str] | None = None,
    expected_outputs: list[str] | None = None,
    task_ref: str | None = None,
    agent_ref: str | None = None,
    retention: str = "discard",
    started_at: datetime | None = None,
) -> Path:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}")
    validate_slug(slug)
    allowed = validate_contract_paths(allowed_paths, "allowed path")
    if not allowed:
        raise ValueError("at least one allowed path is required")
    forbidden = validate_contract_paths(forbidden_paths or [], "forbidden path")
    outputs = validate_contract_paths(expected_outputs or [], "expected output", allow_globs=False)
    commands = validate_verification_commands(verification_commands)
    if retention not in {"discard", "external-archive"}:
        raise ValueError("retention must be discard or external-archive")
    assert_local_process_path(workspace)
    baseline_head = require_git_head(workspace)
    gitignore_before = fingerprint_workspace_path(workspace, ".gitignore")
    ensure_gitignore(workspace)
    gitignore_after = fingerprint_workspace_path(workspace, ".gitignore")
    baseline_changes = capture_dirty_baseline(workspace)

    started = normalize_time(started_at)
    session_key = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{slug}"
    session = workspace / PROCESS_RELATIVE / "sessions" / session_key
    session.mkdir(parents=True, exist_ok=False)
    for directory in SESSION_DIRECTORIES:
        (session / directory).mkdir()

    context = {
        "schema_version": 2,
        "tool": "paperclip",
        "session_key": session_key,
        "domain_slug": slug,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "status": "active",
        "retention": retention,
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "expected_outputs": outputs,
        "verification_commands": commands,
        "baseline_head": baseline_head,
        "baseline_changes": baseline_changes,
    }
    if gitignore_before != gitignore_after:
        context["managed_gitignore_fingerprint"] = gitignore_after
    if task_ref:
        context["task_ref"] = task_ref
    if agent_ref:
        context["agent_ref"] = agent_ref
    context["contract_digest"] = contract_digest(context)
    (session / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (session / "todo.md").write_text(
        "# Process TODO\n\n- [ ] Record the first verifiable action.\n",
        encoding="utf-8",
    )
    (session / "handoff.md").write_text(
        "# Agent Handoff\n\n"
        "## Current state\n\nNot recorded.\n\n"
        "## Evidence\n\nNot recorded.\n\n"
        "## Next action\n\nNot recorded.\n\n"
        "## Risks\n\nNone recorded.\n",
        encoding="utf-8",
    )
    (session / "evidence.md").write_text(
        "# Evidence Index\n\n"
        "| File | Purpose | Captured at (UTC) | Redaction |\n"
        "| --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    return session


def session_path(workspace: Path, session_key: str) -> Path:
    if not SESSION_KEY_RE.fullmatch(session_key):
        raise ValueError("invalid session key")
    session = workspace.resolve() / PROCESS_RELATIVE / "sessions" / session_key
    if session.is_symlink() or not session.is_dir():
        raise ValueError(f"session does not exist as a local directory: {session_key}")
    return session


def load_context(session: Path) -> dict:
    try:
        context = json.loads((session / "context.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read session context: {exc}") from exc
    if not isinstance(context, dict):
        raise ValueError("session context must be a JSON object")
    return context


def run_verification_commands(workspace: Path, commands: list[list[str]], timeout: int) -> list[dict]:
    results = []
    for command in commands:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            result = {
                "command": command,
                "exit_code": completed.returncode,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "status": "passed" if completed.returncode == 0 else "failed",
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {
                "command": command,
                "exit_code": None,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "status": "error",
                "error_type": type(exc).__name__,
            }
        results.append(result)
        if result["status"] != "passed":
            break
    return results


def close_session(
    workspace: Path,
    session_key: str,
    task_title: str | None = None,
    integration_paths: list[str] | None = None,
    archive_ref: str | None = None,
    timeout: int = 600,
) -> dict:
    workspace = workspace.resolve()
    session = session_path(workspace, session_key)
    context = load_context(session)
    if context.get("schema_version") != 2:
        raise ValueError("close requires a version 2 session")
    if not contract_digest_is_valid(context):
        raise ValueError("session contract or status digest does not match")
    if context.get("status") != "active":
        raise ValueError("only an active session can be closed")
    if context.get("retention") == "external-archive" and not archive_ref:
        raise ValueError("--archive-ref is required for external-archive retention")

    todo_path = session / "todo.md"
    todo_text = todo_path.read_text(encoding="utf-8", errors="replace") if todo_path.is_file() else ""
    if re.search(r"^\s*[-*]\s+\[\s\]", todo_text, re.MULTILINE):
        return {
            "closed": False,
            "purged": False,
            "decision": "revise",
            "findings": [{
                "severity": "revise",
                "code": "todo.open",
                "path": str(todo_path.relative_to(workspace)),
                "message": "The session still has unfinished TODO items.",
                "repair": "Complete or explicitly cancel every item before closure.",
            }],
        }

    try:
        from .paperclip_hygiene_checker import analyze
    except ImportError:  # Support direct execution from the skill directory.
        from paperclip_hygiene_checker import analyze

    preflight = analyze(
        workspace,
        phase="work",
        selected_session=session_key,
        allow_paths=integration_paths or [],
        task_title=task_title,
        task_ref=context.get("task_ref"),
        agent_ref=context.get("agent_ref"),
        scan_mode="changed",
    )
    if preflight["decision"] != "allow":
        return {
            "closed": False,
            "purged": False,
            "decision": preflight["decision"],
            "findings": preflight["findings"],
        }

    commands = validate_verification_commands(context.get("verification_commands", []))
    output_results = [
        {"path": relative, "exists": (workspace / relative).exists()}
        for relative in context.get("expected_outputs", [])
    ]
    verification = [] if any(not item["exists"] for item in output_results) else run_verification_commands(
        workspace, commands, timeout
    )
    output_results = [
        {"path": relative, "exists": (workspace / relative).exists()}
        for relative in context.get("expected_outputs", [])
    ]
    delivery = {
        "schema_version": 1,
        "session_key": session_key,
        "generated_at": normalize_time(None).isoformat().replace("+00:00", "Z"),
        "status": "pending",
        "changed_paths": effective_changed_paths(workspace, context, session_key),
        "expected_outputs": output_results,
        "verification": verification,
    }
    delivery["owned_path_fingerprints"] = {
        relative: fingerprint_workspace_path(workspace, relative)
        for relative in delivery["changed_paths"]
    }
    if archive_ref:
        delivery["archive_ref"] = archive_ref
    delivery_path = session / "delivery.json"
    write_delivery(delivery_path, delivery)

    prerequisites_ok = all(item["exists"] for item in output_results) and all(
        item["status"] == "passed" for item in verification
    )
    if not prerequisites_ok:
        delivery["status"] = "blocked"
        write_delivery(delivery_path, delivery)
        prerequisite_findings = []
        if any(not item["exists"] for item in output_results):
            prerequisite_findings.append("One or more expected outputs are missing.")
        if any(item["status"] != "passed" for item in verification):
            prerequisite_findings.append("A verification command failed or could not run.")
        return {
            "closed": False,
            "purged": False,
            "delivery": delivery,
            "decision": "block",
            "findings": prerequisite_findings,
        }

    hygiene = analyze(
        workspace,
        phase="close",
        selected_session=session_key,
        allow_paths=integration_paths or [],
        task_title=task_title,
        task_ref=context.get("task_ref"),
        agent_ref=context.get("agent_ref"),
        scan_mode="changed",
    )
    delivery["hygiene_decision"] = hygiene["decision"]
    if hygiene["decision"] != "allow":
        delivery["status"] = "blocked"
        write_delivery(delivery_path, delivery)
        return {
            "closed": False,
            "purged": False,
            "delivery": delivery,
            "decision": hygiene["decision"],
            "findings": hygiene["findings"],
        }

    closed_at = normalize_time(None).isoformat().replace("+00:00", "Z")
    context["status"] = "closed"
    context["closed_at"] = closed_at
    context["contract_digest"] = contract_digest(context)
    (session / "context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    delivery["status"] = "closed"
    delivery["closed_at"] = closed_at
    write_delivery(delivery_path, delivery)

    no_active_peers = not active_peer_sessions(workspace, session_key)
    purged = context.get("retention") == "discard" and no_active_peers
    if no_active_peers:
        purge_closed_discard_sessions(workspace)
    return {"closed": True, "purged": purged, "delivery": delivery, "decision": "allow"}


def purge_session(workspace: Path, session_key: str, force: bool = False) -> None:
    session = session_path(workspace.resolve(), session_key)
    context = load_context(session)
    if not force and not contract_digest_is_valid(context):
        raise ValueError("refusing to purge a session with a mismatched contract or status digest")
    if not force and context.get("status") != "closed":
        raise ValueError("refusing to purge a session that is not closed; use --force only for abandoned work")
    if not force and context.get("retention") == "external-archive":
        try:
            delivery = json.loads((session / "delivery.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"external archive evidence is missing: {exc}") from exc
        if not isinstance(delivery, dict) or not delivery_digest_is_valid(delivery):
            raise ValueError("external archive delivery digest does not match")
        if delivery.get("status") != "closed" or delivery.get("hygiene_decision") != "allow":
            raise ValueError("external archive delivery did not pass closure")
        if not delivery.get("archive_ref"):
            raise ValueError("external archive evidence is missing")
    shutil.rmtree(session)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--at must be an ISO-8601 timestamp") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage isolated Paperclip process sessions.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a timestamped local process session")
    create.add_argument("--workspace", required=True, help="Target project repository")
    create.add_argument("--slug", required=True, help="Stable domain slug, not a task title or reference")
    create.add_argument("--allow-path", action="append", required=True, help="Project path or glob this session may change; repeatable")
    create.add_argument("--forbid-path", action="append", default=[], help="Project path or glob this session must not change; repeatable")
    create.add_argument("--expect-output", action="append", default=[], help="Concrete project output required at closure; repeatable")
    create.add_argument("--verify-command", action="append", required=True, type=parse_verification_command, help="No-shell verification command; repeatable")
    create.add_argument("--task-ref", help="Opaque Paperclip task reference stored only in context.json")
    create.add_argument("--agent-ref", help="Opaque Paperclip agent reference stored only in context.json")
    create.add_argument("--retention", choices=["discard", "external-archive"], default="discard")
    create.add_argument("--at", type=parse_time, help="Optional ISO-8601 start time; defaults to current UTC")

    close = subparsers.add_parser("close", help="Verify, audit, and close a session")
    close.add_argument("--workspace", required=True)
    close.add_argument("--session", required=True)
    close.add_argument("--task-title", help="Runtime-only task title; prefer PAPERCLIP_TASK_TITLE")
    close.add_argument("--integration-path", action="append", default=[], help="Narrow product-owned Paperclip integration path")
    close.add_argument("--archive-ref", help="Authorized external archive reference")
    close.add_argument("--timeout", type=int, default=600, help="Per-command verification timeout in seconds")

    purge = subparsers.add_parser("purge", help="Delete a closed or explicitly abandoned session")
    purge.add_argument("--workspace", required=True)
    purge.add_argument("--session", required=True)
    purge.add_argument("--force", action="store_true", help="Delete abandoned work that did not close")
    args = parser.parse_args()

    try:
        if args.command == "create":
            session = create_session(
                Path(args.workspace),
                args.slug,
                args.allow_path,
                args.verify_command,
                forbidden_paths=args.forbid_path,
                expected_outputs=args.expect_output,
                task_ref=args.task_ref,
                agent_ref=args.agent_ref,
                retention=args.retention,
                started_at=args.at,
            )
            print(session)
            return 0
        if args.command == "close":
            result = close_session(
                Path(args.workspace),
                args.session,
                task_title=args.task_title or os.getenv("PAPERCLIP_TASK_TITLE"),
                integration_paths=args.integration_path,
                archive_ref=args.archive_ref,
                timeout=args.timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["closed"] else 1
        purge_session(Path(args.workspace), args.session, force=args.force)
        print(f"purged {args.session}")
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
