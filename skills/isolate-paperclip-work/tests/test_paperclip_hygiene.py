import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.paperclip_hygiene_checker import analyze, validate_allow_paths
from scripts.paperclip_session import (
    close_session,
    create_session,
    purge_session,
    validate_slug,
)


FIXED_TIME = datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)
PASS_COMMAND = [[sys.executable, "-c", "raise SystemExit(0)"]]
SESSION_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/paperclip_session.py"


def git(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def initialize_repository(workspace: Path) -> None:
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    (workspace / "README.md").write_text("# Example\n", encoding="utf-8")
    git(workspace, "add", "README.md")
    git(
        workspace,
        "-c", "user.name=Test",
        "-c", "user.email=test@example.com",
        "commit", "-q", "-m", "initial project",
    )


class PaperclipSessionTests(unittest.TestCase):
    def make_session(
        self,
        workspace: Path,
        *,
        retention: str = "discard",
        commands: list[list[str]] | None = None,
        expected_outputs: list[str] | None = None,
    ) -> Path:
        return create_session(
            workspace,
            "payment-timeout",
            ["src/payment/**", "docs/payment-timeout.md"],
            commands or PASS_COMMAND,
            forbidden_paths=["src/payment/secrets/**"],
            expected_outputs=expected_outputs,
            task_ref="PC-1842",
            agent_ref="agent-7",
            retention=retention,
            started_at=FIXED_TIME,
        )

    def test_create_session_initializes_v2_contract_and_ignore_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)

            self.assertEqual("20260715T103000Z-payment-timeout", session.name)
            self.assertEqual(
                {"context.json", "todo.md", "handoff.md", "evidence.md", "notes", "screens", "logs", "scratch"},
                {path.name for path in session.iterdir()},
            )
            context = json.loads((session / "context.json").read_text(encoding="utf-8"))
            self.assertEqual(2, context["schema_version"])
            self.assertEqual(["src/payment/**", "docs/payment-timeout.md"], context["allowed_paths"])
            self.assertEqual(PASS_COMMAND, context["verification_commands"])
            self.assertIn("baseline_head", context)
            self.assertNotIn("task_title", context)
            self.assertIn("/.run/paperclip/", (workspace / ".gitignore").read_text(encoding="utf-8"))
            self.assertEqual("allow", analyze(workspace, selected_session=session.name)["decision"])

    def test_create_requires_git_head_scope_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "allowed path"):
                create_session(workspace, "payment-timeout", [], PASS_COMMAND)

            initialize_repository(workspace)
            with self.assertRaisesRegex(ValueError, "verification command"):
                create_session(workspace, "payment-timeout", ["src/payment"], [])

    def test_cli_create_and_close_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            created = subprocess.run(
                [
                    sys.executable,
                    str(SESSION_SCRIPT),
                    "create",
                    "--workspace", str(workspace),
                    "--slug", "payment-timeout",
                    "--allow-path", "README.md",
                    "--verify-command", f"{sys.executable} -c 'raise SystemExit(0)'",
                    "--task-ref", "PC-1842",
                    "--at", "2026-07-15T10:30:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            session = Path(created.stdout.strip())
            (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")
            closed = subprocess.run(
                [
                    sys.executable,
                    str(SESSION_SCRIPT),
                    "close",
                    "--workspace", str(workspace),
                    "--session", session.name,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(closed.stdout)
            self.assertTrue(result["closed"])
            self.assertTrue(result["purged"])
            self.assertFalse(session.exists())

    def test_slug_rejects_process_oriented_and_non_kebab_names(self) -> None:
        for value in ("task-1842", "paperclip-change", "PaymentTimeout", "payment_timeout"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_slug(value)

    def test_close_blocks_open_todo_then_purges_discard_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)

            blocked = close_session(workspace, session.name)
            self.assertFalse(blocked["closed"])
            self.assertIn("todo.open", {item["code"] for item in blocked["findings"]})
            self.assertTrue(session.exists())

            (session / "todo.md").write_text("# Process TODO\n\n- [x] Verify behavior.\n", encoding="utf-8")
            closed = close_session(workspace, session.name)
            self.assertTrue(closed["closed"])
            self.assertTrue(closed["purged"])
            self.assertFalse(session.exists())

    def test_close_records_external_archive_and_purge_requires_closed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(
                workspace,
                retention="external-archive",
                expected_outputs=["docs/payment-timeout.md"],
            )
            with self.assertRaisesRegex(ValueError, "not closed"):
                purge_session(workspace, session.name)

            (workspace / "docs").mkdir()
            (workspace / "docs/payment-timeout.md").write_text("# Timeout policy\n", encoding="utf-8")
            (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")
            result = close_session(workspace, session.name, archive_ref="audit://records/42")
            self.assertTrue(result["closed"])
            self.assertFalse(result["purged"])
            delivery = json.loads((session / "delivery.json").read_text(encoding="utf-8"))
            self.assertEqual("audit://records/42", delivery["archive_ref"])
            self.assertEqual([{"path": "docs/payment-timeout.md", "exists": True}], delivery["expected_outputs"])
            purge_session(workspace, session.name)
            self.assertFalse(session.exists())

    def test_close_blocks_failed_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            failed = self.make_session(
                workspace,
                commands=[[sys.executable, "-c", "raise SystemExit(3)"]],
                expected_outputs=["docs/payment-timeout.md"],
            )
            (workspace / "docs").mkdir()
            (workspace / "docs/payment-timeout.md").write_text("# Timeout policy\n", encoding="utf-8")
            (failed / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")
            result = close_session(workspace, failed.name)
            self.assertFalse(result["closed"])
            self.assertEqual("block", result["decision"])
            self.assertEqual("blocked", result["delivery"]["status"])
            self.assertIn("verification command", result["findings"][0].lower())
            self.assertTrue(failed.exists())

    def test_close_rechecks_outputs_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            command = [[
                sys.executable,
                "-c",
                "from pathlib import Path; Path('docs/payment-timeout.md').unlink()",
            ]]
            session = self.make_session(
                workspace,
                commands=command,
                expected_outputs=["docs/payment-timeout.md"],
            )
            (workspace / "docs").mkdir()
            (workspace / "docs/payment-timeout.md").write_text("# Timeout policy\n", encoding="utf-8")
            (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")
            result = close_session(workspace, session.name)
            self.assertFalse(result["closed"])
            self.assertIn("expected outputs", result["findings"][0].lower())

    def test_close_attributes_changes_to_peer_sessions_until_all_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            first = create_session(
                workspace,
                "payment-policy",
                ["docs/payment-policy.md"],
                PASS_COMMAND,
                expected_outputs=["docs/payment-policy.md"],
                started_at=FIXED_TIME,
            )
            second = create_session(
                workspace,
                "checkout-policy",
                ["docs/checkout-policy.md"],
                PASS_COMMAND,
                expected_outputs=["docs/checkout-policy.md"],
                started_at=FIXED_TIME + timedelta(seconds=1),
            )
            (workspace / "docs").mkdir()
            (workspace / "docs/payment-policy.md").write_text("# Payment policy\n", encoding="utf-8")
            (workspace / "docs/checkout-policy.md").write_text("# Checkout policy\n", encoding="utf-8")
            for session in (first, second):
                (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")

            first_result = close_session(workspace, first.name)
            self.assertTrue(first_result["closed"])
            self.assertFalse(first_result["purged"])
            self.assertEqual(["docs/payment-policy.md"], first_result["delivery"]["changed_paths"])
            self.assertTrue(first.exists())

            second_result = close_session(workspace, second.name)
            self.assertTrue(second_result["closed"])
            self.assertTrue(second_result["purged"])
            self.assertEqual(["docs/checkout-policy.md"], second_result["delivery"]["changed_paths"])
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_close_preserves_preexisting_dirty_ownership_after_aggregate_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            (workspace / "playing").write_text("legacy marker\n", encoding="utf-8")
            git(workspace, "add", "playing")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "add legacy marker",
            )

            (workspace / "docs").mkdir()
            (workspace / "scripts").mkdir()
            (workspace / "docs/game-type.md").write_text("# Game type\n", encoding="utf-8")
            (workspace / "README.md").write_text("# Existing owner change\n", encoding="utf-8")
            (workspace / "scripts/server.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (workspace / "playing").unlink()
            session = create_session(
                workspace,
                "game-type-docs",
                ["docs/game-type.md"],
                PASS_COMMAND,
                expected_outputs=["docs/game-type.md"],
                started_at=FIXED_TIME,
            )
            (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")

            git(workspace, "add", "-A")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "aggregate workspace changes",
            )

            result = close_session(workspace, session.name)
            self.assertTrue(result["closed"])
            self.assertEqual("allow", result["decision"])
            self.assertEqual(["docs/game-type.md"], result["delivery"]["changed_paths"])

    def test_aggregate_commit_still_blocks_path_created_after_session_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = create_session(
                workspace,
                "game-type-docs",
                ["docs/game-type.md"],
                PASS_COMMAND,
                started_at=FIXED_TIME,
            )
            (workspace / "unclaimed.txt").write_text("unclaimed\n", encoding="utf-8")
            git(workspace, "add", "-A")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "aggregate workspace changes",
            )

            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertEqual("block", report["decision"])
            self.assertIn(
                ("scope.outside", "unclaimed.txt"),
                {(item["code"], item["path"]) for item in report["findings"]},
            )

    def test_peer_session_does_not_hide_unclaimed_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            first = create_session(
                workspace,
                "payment-policy",
                ["docs/payment-policy.md"],
                PASS_COMMAND,
                started_at=FIXED_TIME,
            )
            create_session(
                workspace,
                "checkout-policy",
                ["docs/checkout-policy.md"],
                PASS_COMMAND,
                started_at=FIXED_TIME + timedelta(seconds=1),
            )
            (workspace / "README.md").write_text("# Unclaimed change\n", encoding="utf-8")

            report = analyze(workspace, selected_session=first.name, scan_mode="changed")
            self.assertEqual("block", report["decision"])
            self.assertIn("scope.outside", {item["code"] for item in report["findings"]})

    def test_external_archive_closure_cleans_closed_discard_peer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            discard = create_session(
                workspace,
                "payment-policy",
                ["docs/payment-policy.md"],
                PASS_COMMAND,
                expected_outputs=["docs/payment-policy.md"],
                started_at=FIXED_TIME,
            )
            archive = create_session(
                workspace,
                "checkout-policy",
                ["docs/checkout-policy.md"],
                PASS_COMMAND,
                expected_outputs=["docs/checkout-policy.md"],
                retention="external-archive",
                started_at=FIXED_TIME + timedelta(seconds=1),
            )
            (workspace / "docs").mkdir()
            (workspace / "docs/payment-policy.md").write_text("# Payment policy\n", encoding="utf-8")
            (workspace / "docs/checkout-policy.md").write_text("# Checkout policy\n", encoding="utf-8")
            for session in (discard, archive):
                (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")

            self.assertTrue(close_session(workspace, discard.name)["closed"])
            archive_result = close_session(workspace, archive.name, archive_ref="audit://records/42")
            self.assertTrue(archive_result["closed"])
            self.assertFalse(archive_result["purged"])
            self.assertFalse(discard.exists())
            self.assertTrue(archive.exists())

    def test_manual_status_edit_cannot_bypass_purge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace, retention="external-archive")
            context_path = session / "context.json"
            context = json.loads(context_path.read_text(encoding="utf-8"))
            context["status"] = "closed"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                purge_session(workspace, session.name)


class PaperclipHygieneCheckerTests(unittest.TestCase):
    def make_session(self, workspace: Path, retention: str = "discard") -> Path:
        return create_session(
            workspace,
            "payment-timeout",
            ["src/payment/**", "docs/payment-timeout.md"],
            PASS_COMMAND,
            forbidden_paths=["src/payment/secrets/**"],
            task_ref="PC-1842",
            agent_ref="agent-7",
            retention=retention,
            started_at=FIXED_TIME,
        )

    def test_preexisting_dirty_file_is_ignored_until_agent_changes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            (workspace / "README.md").write_text("# User change\n", encoding="utf-8")
            session = self.make_session(workspace)

            clean_report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertEqual("allow", clean_report["decision"])
            (workspace / "README.md").write_text("# Agent overwrote user change\n", encoding="utf-8")
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertEqual("block", report["decision"])
            self.assertIn("scope.outside", {item["code"] for item in report["findings"]})

    def test_scope_allows_owned_path_and_blocks_forbidden_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            (workspace / "src/payment").mkdir(parents=True)
            (workspace / "src/payment/policy.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
            self.assertEqual(
                "allow",
                analyze(workspace, selected_session=session.name, scan_mode="changed")["decision"],
            )

            (workspace / "src/payment/secrets").mkdir()
            (workspace / "src/payment/secrets/key.py").write_text("KEY_NAME = 'redacted'\n", encoding="utf-8")
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertEqual("block", report["decision"])
            self.assertIn("scope.forbidden", {item["code"] for item in report["findings"]})

    def test_scope_contract_tampering_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            context_path = session / "context.json"
            context = json.loads(context_path.read_text(encoding="utf-8"))
            context["allowed_paths"] = ["src/**"]
            context_path.write_text(json.dumps(context), encoding="utf-8")
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertEqual("block", report["decision"])
            self.assertIn("scope.contract_tampered", {item["code"] for item in report["findings"]})

    def test_committed_out_of_scope_path_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            (workspace / "README.md").write_text("# Out of scope\n", encoding="utf-8")
            git(workspace, "add", "README.md")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "update project entry",
            )
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertIn("scope.outside", {item["code"] for item in report["findings"]})

    def test_reverted_commit_still_counts_as_out_of_scope_touch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            (workspace / "README.md").write_text("# Temporary out-of-scope edit\n", encoding="utf-8")
            git(workspace, "add", "README.md")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "temporary entry change",
            )
            (workspace / "README.md").write_text("# Example\n", encoding="utf-8")
            git(workspace, "add", "README.md")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "restore project entry",
            )
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertIn("scope.outside", {item["code"] for item in report["findings"]})

    def test_session_commit_subject_and_branch_reject_task_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            git(workspace, "checkout", "-q", "-b", "PC-1842-payment-timeout")
            (workspace / "docs").mkdir()
            (workspace / "docs/payment-timeout.md").write_text("# Timeout policy\n", encoding="utf-8")
            git(workspace, "add", "docs/payment-timeout.md")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "complete PC-1842",
            )
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("git.task_ref.branch", codes)
            self.assertIn("git.task_ref.commit", codes)

    def test_session_managed_gitignore_can_be_committed_without_expanding_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            git(workspace, "add", ".gitignore")
            git(
                workspace,
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "ignore local execution state",
            )
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            self.assertEqual("allow", report["decision"])
            self.assertNotIn(".gitignore", report["changed_paths"])

    def test_task_and_agent_references_in_project_assets_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            (workspace / "docs").mkdir()
            (workspace / "docs/payment-timeout.md").write_text(
                "Implemented for PC-1842 by agent-7.\n",
                encoding="utf-8",
            )
            report = analyze(workspace, selected_session=session.name, scan_mode="changed")
            codes = {item["code"] for item in report["findings"]}
            self.assertEqual("block", report["decision"])
            self.assertIn("leak.task_ref.content", codes)
            self.assertIn("leak.agent_ref.content", codes)

    def test_staged_scan_reads_index_instead_of_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            target = workspace / "README.md"
            target.write_text("Paperclip task PC-1842\n", encoding="utf-8")
            git(workspace, "add", "README.md")
            target.write_text("# Clean worktree copy\n", encoding="utf-8")
            report = analyze(workspace, task_ref="PC-1842", scan_mode="staged")
            self.assertEqual("block", report["decision"])
            self.assertIn("leak.task_ref.content", {item["code"] for item in report["findings"]})

    def test_runtime_task_title_flags_derived_path_and_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            source = workspace / "src/fix-payment-timeout-behavior.py"
            source.parent.mkdir()
            source.write_text("class FixPaymentTimeoutBehavior:\n    pass\n", encoding="utf-8")
            report = analyze(
                workspace,
                task_title="Fix payment timeout behavior",
                scan_mode="repository",
            )
            codes = {item["code"] for item in report["findings"]}
            self.assertEqual("revise", report["decision"])
            self.assertIn("naming.task_title_path", codes)
            self.assertIn("naming.task_title_identifier", codes)

    def test_process_dependency_and_paperclip_runtime_language_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "docs").mkdir()
            (workspace / "docs/implementation.md").write_text(
                "See `.run/paperclip/sessions/current` for the Paperclip task status.\n",
                encoding="utf-8",
            )
            report = analyze(workspace)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("leak.process_dependency", codes)
            self.assertIn("leak.paperclip_context", codes)

    def test_task_shaped_path_requires_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "docs").mkdir()
            (workspace / "docs/task-1842.md").write_text("Stable content.\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("revise", report["decision"])
            self.assertIn("naming.task_shaped", {item["code"] for item in report["findings"]})

    def test_screenshots_require_standard_names_and_index_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            (session / "screens/before.png").write_bytes(b"not-a-real-image")
            report = analyze(workspace, selected_session=session.name)
            self.assertIn("screens.naming", {item["code"] for item in report["findings"]})

            (session / "screens/before.png").rename(session / "screens/001-before-checkout.png")
            report = analyze(workspace, selected_session=session.name)
            self.assertIn("screens.unindexed", {item["code"] for item in report["findings"]})
            with (session / "evidence.md").open("a", encoding="utf-8") as stream:
                stream.write("| 001-before-checkout.png | Baseline | 2026-07-15T10:31:00Z | redacted |\n")
            self.assertEqual("allow", analyze(workspace, selected_session=session.name)["decision"])

    def test_secret_pattern_in_process_artifact_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            (session / "logs/001-request.log").write_text(
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n",
                encoding="utf-8",
            )
            report = analyze(workspace, selected_session=session.name)
            self.assertEqual("block", report["decision"])
            self.assertIn("process.secret", {item["code"] for item in report["findings"]})

    def test_tracked_process_artifact_blocks_even_when_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            git(workspace, "add", "-f", ".run/paperclip")
            report = analyze(workspace, selected_session=session.name)
            self.assertEqual("block", report["decision"])
            self.assertIn("process.tracked", {item["code"] for item in report["findings"]})

    def test_symlinked_sessions_directory_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".run/paperclip").mkdir(parents=True)
            (workspace / ".gitignore").write_text("/.run/paperclip/\n", encoding="utf-8")
            external = workspace / "external-sessions"
            external.mkdir()
            (workspace / ".run/paperclip/sessions").symlink_to(external, target_is_directory=True)
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("process.sessions_symlink", {item["code"] for item in report["findings"]})

    def test_selected_session_audit_does_not_own_malformed_peer_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            selected = self.make_session(workspace)
            peer = workspace / ".run/paperclip/sessions/20260715T103001Z-browser-evidence"
            (peer / "scratch").mkdir(parents=True)
            (peer / "scratch/runtime-link").symlink_to(workspace / "README.md")

            report = analyze(workspace, selected_session=selected.name, scan_mode="changed")
            self.assertEqual("allow", report["decision"])
            self.assertNotIn(
                "process.nested_symlink",
                {item["code"] for item in report["findings"]},
            )

    def test_allow_path_never_hides_current_task_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            integration = workspace / "src/integrations/paperclip"
            integration.mkdir(parents=True)
            (integration / "client.py").write_text(
                "description = 'Paperclip task API for PC-1842'\n",
                encoding="utf-8",
            )
            report = analyze(
                workspace,
                selected_session=session.name,
                allow_paths=["src/integrations/paperclip"],
            )
            self.assertEqual("block", report["decision"])
            self.assertIn("leak.task_ref.content", {item["code"] for item in report["findings"]})

        with self.assertRaisesRegex(ValueError, "too broad"):
            validate_allow_paths(["src"])

    def test_allow_path_accepts_intentional_process_integration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            integration = workspace / "src/integrations/paperclip"
            integration.mkdir(parents=True)
            (integration / "runtime.py").write_text(
                "PROCESS_ROOT = '.run/paperclip'\n",
                encoding="utf-8",
            )

            report = analyze(
                workspace,
                allow_paths=["src/integrations/paperclip/runtime.py"],
            )
            self.assertEqual("allow", report["decision"])
            self.assertNotIn("leak.process_dependency", {item["code"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
