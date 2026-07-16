#!/usr/bin/env python3
import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SESSION_KEY_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9]+(?:-[a-z0-9]+)*$")
PROHIBITED_SLUG_PARTS = {"agent", "paperclip", "session", "task", "temp", "temporary", "todo", "wip"}
PROCESS_RELATIVE = Path(".run/paperclip")
LIFECYCLE_LOCK_NAME = ".lifecycle.lock"
LEGACY_CONTEXT_BACKUP = "overlap-migration-backup.json"
COMMITTED_OWNERSHIP_FILE = "committed-path-ownership.json"
SESSION_DIRECTORIES = ("notes", "screens", "logs", "scratch")
BROAD_CONTRACT_PATHS = {".", "*", "**", "./**"}
CONTRACT_FIELDS = (
    "schema_version", "tool", "session_key", "domain_slug", "started_at", "status", "closed_at", "retention",
    "allowed_paths", "forbidden_paths", "expected_outputs", "verification_commands",
    "baseline_head", "baseline_changes", "overlapping_session_keys", "managed_gitignore_fingerprint",
    "task_ref", "agent_ref",
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


def committed_ownership_digest(manifest: dict) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ownership_scope_digest(context: dict) -> str:
    fields = (
        "schema_version", "session_key", "allowed_paths", "forbidden_paths",
        "baseline_head", "baseline_changes", "overlapping_session_keys",
    )
    payload = {key: context[key] for key in fields if key in context}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


@contextmanager
def workspace_lifecycle_lock(workspace: Path):
    workspace = workspace.resolve()
    assert_local_process_path(workspace)
    lock_root = Path(tempfile.gettempdir()) / f"paperclip-workspace-locks-{os.getuid()}"
    lock_root.mkdir(mode=0o700, exist_ok=True)
    if lock_root.is_symlink() or not lock_root.is_dir():
        raise ValueError(f"workspace lifecycle lock directory is not a local directory: {lock_root}")
    lock_stat = lock_root.stat()
    if lock_stat.st_uid != os.getuid() or lock_stat.st_mode & 0o077:
        raise ValueError(f"workspace lifecycle lock directory has unsafe ownership or permissions: {lock_root}")
    workspace_key = hashlib.sha256(os.fsencode(workspace)).hexdigest()
    lock_path = lock_root / f"{workspace_key}{LIFECYCLE_LOCK_NAME}"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"unable to open workspace lifecycle lock: {exc}") from exc
    try:
        with os.fdopen(descriptor, "a+") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise ValueError(f"unable to use workspace lifecycle lock: {exc}") from exc


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


def fingerprint_git_path(workspace: Path, revision: str, relative: str) -> str:
    tree = git_command(workspace, "ls-tree", "-z", revision, "--", relative)
    if tree is None or tree.returncode != 0:
        raise ValueError(f"unable to inspect {relative} at session baseline")
    entries = [entry for entry in tree.stdout.split(b"\0") if entry]
    if not entries:
        return "missing"
    metadata, separator, tree_path = entries[0].partition(b"\t")
    fields = metadata.split()
    if not separator or len(fields) != 3 or tree_path.decode("utf-8", errors="surrogateescape") != relative:
        raise ValueError(f"unable to inspect {relative} at session baseline")
    mode, object_type, object_id = (field.decode("ascii", errors="strict") for field in fields)
    if object_type != "blob":
        return "non-file"
    content = git_command(workspace, "cat-file", "blob", object_id)
    if content is None or content.returncode != 0:
        raise ValueError(f"unable to read {relative} at session baseline")
    if mode == "120000":
        return f"symlink:{content.stdout.decode('utf-8', errors='surrogateescape')}"
    return f"sha256:{hashlib.sha256(content.stdout).hexdigest()}"


def capture_dirty_baseline(workspace: Path) -> dict[str, dict[str, str]]:
    process = PROCESS_RELATIVE.as_posix()
    return {
        relative: {"status": status, "fingerprint": fingerprint_workspace_path(workspace, relative)}
        for relative, status in git_status_entries(workspace).items()
        if relative != process and not relative.startswith(f"{process}/")
    }


def commit_tree_and_parents(workspace: Path, revision: str) -> tuple[bytes, tuple[bytes, ...]] | None:
    result = git_command(workspace, "show", "-s", "--format=%T%x00%P", revision)
    if result is None or result.returncode != 0:
        return None
    tree, separator, parents = result.stdout.rstrip(b"\n").partition(b"\0")
    if not separator or not tree:
        return None
    return tree, tuple(parents.split())


def committed_paths_since(workspace: Path, baseline_head: str) -> set[str]:
    baseline_identity = commit_tree_and_parents(workspace, baseline_head)
    head_identity = commit_tree_and_parents(workspace, "HEAD")
    if baseline_identity is not None and baseline_identity == head_identity:
        # Another workspace actor may amend only commit metadata after this
        # session captures its baseline. Identical trees and parent lists prove
        # no project path changed; a real follow-up or revert changes parents.
        return set()
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


def commit_changed_paths(workspace: Path, revision: str) -> set[str]:
    result = git_command(
        workspace, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-m", "-z", revision,
    )
    if result is None or result.returncode != 0:
        raise ValueError(f"unable to inspect commit {revision[:12]}")
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def resolve_commit(workspace: Path, revision: str) -> str:
    result = git_command(workspace, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if result is None or result.returncode != 0:
        raise ValueError(f"invalid commit: {revision}")
    return result.stdout.decode("ascii", errors="strict").strip()


def commit_is_ancestor(workspace: Path, ancestor: str, descendant: str) -> bool:
    result = git_command(workspace, "merge-base", "--is-ancestor", ancestor, descendant)
    return result is not None and result.returncode == 0


def path_history_digest(workspace: Path, revision: str, relative: str) -> str:
    result = git_command(workspace, "log", "--format=%H", f"{revision}..HEAD", "--", relative)
    if result is None or result.returncode != 0:
        raise ValueError(f"unable to inspect committed history for {relative}")
    return hashlib.sha256(result.stdout).hexdigest()


def load_committed_ownership(workspace: Path, session_key: str, context: dict) -> dict | None:
    path = session_path(workspace, session_key) / COMMITTED_OWNERSHIP_FILE
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("source_session_key") != session_key
        or manifest.get("source_contract_digest") != context.get("contract_digest")
        or manifest.get("manifest_digest") != committed_ownership_digest(manifest)
        or not isinstance(manifest.get("records"), list)
    ):
        return None
    return manifest


def committed_ownership_claims_path(
    workspace: Path,
    session_key: str,
    context: dict,
    relative: str,
) -> bool:
    manifest = load_committed_ownership(workspace, session_key, context)
    if manifest is None:
        return False
    for record in manifest["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("paths"), dict):
            continue
        evidence = record["paths"].get(relative)
        revision = record.get("commit")
        if not isinstance(evidence, dict) or not isinstance(revision, str):
            continue
        try:
            if (
                resolve_commit(workspace, revision) != revision
                or not commit_is_ancestor(workspace, revision, "HEAD")
                or relative not in commit_changed_paths(workspace, revision)
                or fingerprint_git_path(workspace, revision, relative) != evidence.get("commit_fingerprint")
                or fingerprint_git_path(workspace, "HEAD", relative) != evidence.get("head_fingerprint")
                or path_history_digest(workspace, revision, relative) != evidence.get("post_commit_history_digest")
            ):
                continue
        except ValueError:
            continue
        owner = record.get("owner")
        if not isinstance(owner, dict):
            continue
        if owner.get("kind") != "session" or not isinstance(owner.get("session_key"), str):
            continue
        owner_key = owner["session_key"]
        try:
            owner_context = load_context(session_path(workspace, owner_key))
            owner_allowed = validate_contract_paths(owner_context.get("allowed_paths", []), "allowed path")
            owner_forbidden = validate_contract_paths(owner_context.get("forbidden_paths", []), "forbidden path")
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if (
            contract_digest_is_valid(owner_context)
            and owner.get("scope_digest") == ownership_scope_digest(owner_context)
            and sessions_overlap(session_key, context, owner_key, owner_context)
            and path_matches_contract(relative, owner_allowed)
            and not path_matches_contract(relative, owner_forbidden)
        ):
            return True
    return False


def _attest_committed_paths_unlocked(
    workspace: Path,
    session_key: str,
    revision: str,
    paths: list[str],
    owner_session_key: str,
) -> dict:
    session = session_path(workspace, session_key)
    context = load_context(session)
    if context.get("status") != "active" or not contract_digest_is_valid(context):
        raise ValueError("committed ownership requires an active session with a valid contract digest")
    normalized_paths = validate_contract_paths(paths, "committed ownership path", allow_globs=False)
    if not normalized_paths:
        raise ValueError("at least one committed ownership path is required")
    commit = resolve_commit(workspace, revision)
    baseline = context.get("baseline_head")
    if not isinstance(baseline, str) or commit == baseline or not commit_is_ancestor(workspace, baseline, commit):
        raise ValueError("commit must be after the source session baseline")
    if not commit_is_ancestor(workspace, commit, "HEAD"):
        raise ValueError("commit must be an ancestor of HEAD")
    changed = commit_changed_paths(workspace, commit)
    missing = [relative for relative in normalized_paths if relative not in changed]
    if missing:
        raise ValueError(f"path was not changed by commit {commit[:12]}: {missing[0]}")

    if owner_session_key == session_key:
        raise ValueError("owner session must differ from source session")
    owner_context = load_context(session_path(workspace, owner_session_key))
    if not contract_digest_is_valid(owner_context) or owner_context.get("status") not in {"active", "closed"}:
        raise ValueError("owner session contract is not valid ownership evidence")
    if not sessions_overlap(session_key, context, owner_session_key, owner_context):
        raise ValueError("owner session does not overlap the source session")
    owner_allowed = validate_contract_paths(owner_context.get("allowed_paths", []), "allowed path")
    owner_forbidden = validate_contract_paths(owner_context.get("forbidden_paths", []), "forbidden path")
    for relative in normalized_paths:
        if not path_matches_contract(relative, owner_allowed) or path_matches_contract(relative, owner_forbidden):
            raise ValueError(f"owner session contract does not own path: {relative}")
    owner = {
        "kind": "session",
        "session_key": owner_session_key,
        "scope_digest": ownership_scope_digest(owner_context),
    }

    evidence = {}
    for relative in normalized_paths:
        head_fingerprint = fingerprint_git_path(workspace, "HEAD", relative)
        if fingerprint_workspace_path(workspace, relative) != head_fingerprint:
            raise ValueError(f"refusing to attest a path with uncommitted changes: {relative}")
        evidence[relative] = {
            "commit_fingerprint": fingerprint_git_path(workspace, commit, relative),
            "head_fingerprint": head_fingerprint,
            "post_commit_history_digest": path_history_digest(workspace, commit, relative),
        }

    manifest = load_committed_ownership(workspace, session_key, context) or {
        "schema_version": 1,
        "source_session_key": session_key,
        "source_contract_digest": context["contract_digest"],
        "records": [],
    }
    record = {
        "commit": commit,
        "commit_tree": commit_tree_and_parents(workspace, commit)[0].decode("ascii"),
        "owner": owner,
        "paths": evidence,
        "attested_at": normalize_time(None).isoformat().replace("+00:00", "Z"),
    }
    selected_paths = set(normalized_paths)
    manifest["records"] = [
        existing for existing in manifest["records"]
        if not isinstance(existing, dict)
        or not isinstance(existing.get("paths"), dict)
        or selected_paths.isdisjoint(existing["paths"])
    ]
    manifest["records"].append(record)
    manifest["manifest_digest"] = committed_ownership_digest(manifest)
    destination = session / COMMITTED_OWNERSHIP_FILE
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return record


def attest_committed_paths(
    workspace: Path,
    session_key: str,
    revision: str,
    paths: list[str],
    owner_session_key: str,
) -> dict:
    workspace = workspace.resolve()
    with workspace_lifecycle_lock(workspace):
        return _attest_committed_paths_unlocked(
            workspace, session_key, revision, paths,
            owner_session_key=owner_session_key,
        )


def validate_session_key_list(value: object, field: str = "overlapping_session_keys") -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of session keys")
    invalid = [item for item in value if not SESSION_KEY_RE.fullmatch(item)]
    if invalid:
        raise ValueError(f"invalid {field}: {invalid[0]}")
    return list(dict.fromkeys(value))


def sessions_overlap(
    selected_session_key: str,
    selected_context: dict,
    peer_session_key: str,
    peer_context: dict,
) -> bool:
    try:
        selected_peers = validate_session_key_list(selected_context.get("overlapping_session_keys", []))
        peer_peers = validate_session_key_list(peer_context.get("overlapping_session_keys", []))
    except ValueError:
        return False
    return peer_session_key in selected_peers or selected_session_key in peer_peers


def path_changed_since_session_baseline(workspace: Path, context: dict, relative: str) -> bool:
    baseline_head = context.get("baseline_head")
    baseline = context.get("baseline_changes")
    if not isinstance(baseline_head, str) or not isinstance(baseline, dict):
        return False
    record = baseline.get(relative)
    if record is not None:
        if not isinstance(record, dict) or not isinstance(record.get("fingerprint"), str):
            return False
        baseline_fingerprint = record["fingerprint"]
    else:
        try:
            baseline_fingerprint = fingerprint_git_path(workspace, baseline_head, relative)
        except ValueError:
            return False
    return baseline_fingerprint != fingerprint_workspace_path(workspace, relative)


def peer_session_claims_path(
    workspace: Path,
    selected_session_key: str,
    selected_context: dict,
    relative: str,
) -> bool:
    try:
        selected_allowed = validate_contract_paths(selected_context.get("allowed_paths", []), "allowed path")
        selected_forbidden = validate_contract_paths(selected_context.get("forbidden_paths", []), "forbidden path")
    except (AttributeError, TypeError, ValueError):
        return False
    if path_matches_contract(relative, selected_allowed) or path_matches_contract(relative, selected_forbidden):
        return False
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
            or not sessions_overlap(selected_session_key, selected_context, session.name, context)
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
            if path_changed_since_session_baseline(workspace, context, relative):
                return True
            try:
                expected_outputs = validate_contract_paths(
                    context.get("expected_outputs", []), "expected output", allow_globs=False
                )
            except (AttributeError, TypeError, ValueError):
                continue
            baseline = context.get("baseline_changes", {})
            record = baseline.get(relative) if isinstance(baseline, dict) else None
            if (
                relative in expected_outputs
                and isinstance(record, dict)
                and record.get("fingerprint") == fingerprint_workspace_path(workspace, relative)
            ):
                return True
            continue
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
    committed = committed_paths_since(workspace, baseline_head)
    if selected_session_key:
        committed = {
            relative for relative in committed
            if not committed_ownership_claims_path(workspace, selected_session_key, context, relative)
        }
    effective = set(committed)
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
        or not (
            relative in baseline
            and isinstance(baseline[relative], dict)
            and baseline[relative].get("fingerprint")
            == fingerprint_workspace_path(workspace, relative)
        )
        and not peer_session_claims_path(workspace, selected_session_key, context, relative)
    ]


def owned_commit_revisions(workspace: Path, context: dict, selected_session_key: str) -> list[str]:
    baseline_head = context.get("baseline_head")
    if not isinstance(baseline_head, str):
        return []
    owned_paths = set(effective_changed_paths(workspace, context, selected_session_key))
    revisions = git_command(workspace, "rev-list", "--reverse", f"{baseline_head}..HEAD")
    if revisions is None or revisions.returncode != 0:
        return []
    return [
        revision
        for revision in revisions.stdout.decode("ascii", errors="strict").splitlines()
        if commit_changed_paths(workspace, revision).intersection(owned_paths)
    ]


def active_peer_sessions(
    workspace: Path,
    selected_session_key: str,
    selected_context: dict | None = None,
) -> list[Path]:
    sessions_root = workspace / PROCESS_RELATIVE / "sessions"
    peers = []
    if not sessions_root.is_dir() or sessions_root.is_symlink():
        return peers
    if selected_context is None:
        try:
            selected_context = load_context(session_path(workspace, selected_session_key))
        except (OSError, ValueError):
            return peers
    for session in sessions_root.iterdir():
        if session.name == selected_session_key:
            continue
        if session.is_symlink() or not session.is_dir():
            peers.append(session)
            continue
        try:
            context = json.loads((session / "context.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            peers.append(session)
            continue
        if not isinstance(context, dict) or context.get("schema_version") != 2:
            peers.append(session)
            continue
        try:
            selected_peers = validate_session_key_list(selected_context.get("overlapping_session_keys", []))
            peer_peers = validate_session_key_list(context.get("overlapping_session_keys", []))
        except ValueError:
            peers.append(session)
            continue
        overlaps = session.name in selected_peers or selected_session_key in peer_peers
        if not contract_digest_is_valid(context) or (overlaps and context.get("status") == "active"):
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
            and not active_peer_sessions(workspace, session.name, context)
        ):
            shutil.rmtree(session)


def active_session_keys(workspace: Path) -> list[str]:
    sessions_root = workspace / PROCESS_RELATIVE / "sessions"
    if not sessions_root.is_dir() or sessions_root.is_symlink():
        return []
    keys = []
    for session in sessions_root.iterdir():
        if not session.is_dir() or session.is_symlink() or not SESSION_KEY_RE.fullmatch(session.name):
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
            keys.append(session.name)
    return sorted(keys)


def _create_session_unlocked(
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
    overlapping_session_keys = active_session_keys(workspace)

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
        "overlapping_session_keys": overlapping_session_keys,
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
    with workspace_lifecycle_lock(workspace):
        return _create_session_unlocked(
            workspace,
            slug,
            allowed_paths,
            verification_commands,
            forbidden_paths=forbidden_paths,
            expected_outputs=expected_outputs,
            task_ref=task_ref,
            agent_ref=agent_ref,
            retention=retention,
            started_at=started_at,
        )


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


def write_context(path: Path, context: dict) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(context, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def legacy_session_interval(session: Path, context: dict) -> tuple[datetime, datetime | None] | None:
    session_key = session.name
    if (
        context.get("schema_version") != 2
        or context.get("session_key") != session_key
        or not contract_digest_is_valid(context)
    ):
        return None
    started_at = context.get("started_at")
    if not isinstance(started_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        return None
    started = started.astimezone(timezone.utc)
    if not session_key.startswith(f"{started.strftime('%Y%m%dT%H%M%SZ')}-"):
        return None

    status = context.get("status")
    if status == "active":
        return (started, None) if "closed_at" not in context else None
    if status != "closed":
        return None
    closed_at = context.get("closed_at")
    if not isinstance(closed_at, str):
        return None
    try:
        closed = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if closed.tzinfo is None:
        return None
    closed = closed.astimezone(timezone.utc)
    if closed < started:
        return None
    try:
        delivery = json.loads((session / "delivery.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(delivery, dict)
        or not delivery_digest_is_valid(delivery)
        or delivery.get("session_key") != session_key
        or delivery.get("status") != "closed"
        or delivery.get("closed_at") != closed_at
        or delivery.get("hygiene_decision") != "allow"
    ):
        return None
    return started, closed


def session_intervals_overlap(
    selected: tuple[datetime, datetime | None],
    peer: tuple[datetime, datetime | None],
) -> bool:
    selected_started, selected_closed = selected
    peer_started, peer_closed = peer
    return (
        (selected_closed is None or peer_started < selected_closed)
        and (peer_closed is None or selected_started < peer_closed)
    )


def legacy_overlap_peer_keys(workspace: Path, selected_session_key: str) -> list[str]:
    sessions_root = workspace / PROCESS_RELATIVE / "sessions"
    if not sessions_root.is_dir() or sessions_root.is_symlink():
        return []
    try:
        selected_context = load_context(session_path(workspace, selected_session_key))
    except ValueError:
        return []
    selected_interval = legacy_session_interval(session_path(workspace, selected_session_key), selected_context)
    if selected_interval is None:
        return []

    peers = []
    for session in sessions_root.iterdir():
        if (
            session.name == selected_session_key
            or not session.is_dir()
            or session.is_symlink()
            or not SESSION_KEY_RE.fullmatch(session.name)
        ):
            continue
        try:
            peer_context = load_context(session)
        except ValueError:
            continue
        peer_interval = legacy_session_interval(session, peer_context)
        if peer_interval is not None and session_intervals_overlap(selected_interval, peer_interval):
            peers.append(session.name)
    return sorted(peers)


def _migrate_legacy_context_unlocked(
    workspace: Path,
    session_key: str,
    rollback: bool = False,
) -> dict:
    workspace = workspace.resolve()
    session = session_path(workspace, session_key)
    context_path = session / "context.json"
    backup_path = session / "scratch" / LEGACY_CONTEXT_BACKUP
    if rollback:
        if not backup_path.is_file() or backup_path.is_symlink():
            raise ValueError("legacy context migration backup is missing")
        context = load_context(session)
        if (
            context.get("schema_version") != 2
            or "overlapping_session_keys" not in context
            or not contract_digest_is_valid(context)
        ):
            raise ValueError("current context is not a valid migrated version 2 contract")
        try:
            backup = json.loads(backup_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"unable to read legacy context migration backup: {exc}") from exc
        if (
            not isinstance(backup, dict)
            or backup.get("schema_version") != 1
            or not isinstance(backup.get("legacy_contract_digest"), str)
        ):
            raise ValueError("legacy context migration backup is invalid")
        restored = dict(context)
        restored.pop("overlapping_session_keys")
        restored["contract_digest"] = backup["legacy_contract_digest"]
        if not contract_digest_is_valid(restored):
            raise ValueError("legacy context migration backup does not match the current contract")
        write_context(context_path, restored)
        return {"session": session_key, "rolled_back": True, "migrated": False}

    context = load_context(session)
    if context.get("schema_version") != 2:
        raise ValueError("migration requires a version 2 session")
    if not contract_digest_is_valid(context):
        raise ValueError("refusing to migrate a context with a mismatched contract digest")
    if "overlapping_session_keys" in context:
        validate_session_key_list(context["overlapping_session_keys"])
        return {"session": session_key, "rolled_back": False, "migrated": False}
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup = {
        "schema_version": 1,
        "legacy_contract_digest": context["contract_digest"],
    }
    if backup_path.exists():
        try:
            existing_backup = json.loads(backup_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"unable to read legacy context migration backup: {exc}") from exc
        if existing_backup != backup:
            raise ValueError("legacy context migration backup does not match this contract")
    else:
        write_context(backup_path, backup)
    context["overlapping_session_keys"] = legacy_overlap_peer_keys(workspace, session_key)
    context["contract_digest"] = contract_digest(context)
    write_context(context_path, context)
    return {
        "session": session_key,
        "rolled_back": False,
        "migrated": True,
        "overlapping_session_keys": context["overlapping_session_keys"],
    }


def migrate_legacy_context(
    workspace: Path,
    session_key: str,
    rollback: bool = False,
) -> dict:
    workspace = workspace.resolve()
    with workspace_lifecycle_lock(workspace):
        return _migrate_legacy_context_unlocked(workspace, session_key, rollback=rollback)


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


def _close_session_unlocked(
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

    no_active_peers = not active_peer_sessions(workspace, session_key, context)
    purged = context.get("retention") == "discard" and no_active_peers
    if no_active_peers:
        purge_closed_discard_sessions(workspace)
    return {"closed": True, "purged": purged, "delivery": delivery, "decision": "allow"}


def close_session(
    workspace: Path,
    session_key: str,
    task_title: str | None = None,
    integration_paths: list[str] | None = None,
    archive_ref: str | None = None,
    timeout: int = 600,
) -> dict:
    workspace = workspace.resolve()
    with workspace_lifecycle_lock(workspace):
        return _close_session_unlocked(
            workspace,
            session_key,
            task_title=task_title,
            integration_paths=integration_paths,
            archive_ref=archive_ref,
            timeout=timeout,
        )


def _purge_session_unlocked(workspace: Path, session_key: str, force: bool = False) -> None:
    session = session_path(workspace.resolve(), session_key)
    context = load_context(session)
    if not force and not contract_digest_is_valid(context):
        raise ValueError("refusing to purge a session with a mismatched contract or status digest")
    if not force and context.get("status") != "closed":
        raise ValueError("refusing to purge a session that is not closed; use --force only for abandoned work")
    if not force and active_peer_sessions(workspace, session_key, context):
        raise ValueError("refusing to purge ownership evidence while an overlapping session is active")
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


def purge_session(workspace: Path, session_key: str, force: bool = False) -> None:
    workspace = workspace.resolve()
    with workspace_lifecycle_lock(workspace):
        _purge_session_unlocked(workspace, session_key, force=force)


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

    migrate = subparsers.add_parser("migrate", help="Add overlap metadata to a legacy version 2 session")
    migrate.add_argument("--workspace", required=True)
    migrate.add_argument("--session", required=True)
    migrate.add_argument("--rollback", action="store_true", help="Restore the validated pre-migration context")

    attest = subparsers.add_parser("attest-commit", help="Move committed paths to their verified owner without changing session scope")
    attest.add_argument("--workspace", required=True)
    attest.add_argument("--session", required=True, help="Source session currently charged for the paths")
    attest.add_argument("--commit", required=True, help="Commit that introduced the cross-session paths")
    attest.add_argument("--path", action="append", required=True, help="Concrete committed path; repeatable")
    attest.add_argument("--owner-session", required=True, help="Overlapping session whose valid contract owns every path")
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
        if args.command == "migrate":
            result = migrate_legacy_context(Path(args.workspace), args.session, rollback=args.rollback)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "attest-commit":
            result = attest_committed_paths(
                Path(args.workspace), args.session, args.commit, args.path,
                owner_session_key=args.owner_session,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        purge_session(Path(args.workspace), args.session, force=args.force)
        print(f"purged {args.session}")
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
