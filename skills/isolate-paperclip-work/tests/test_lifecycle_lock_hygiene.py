import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.paperclip_hygiene_checker import analyze
from scripts.paperclip_session import close_session, create_session


PASS_COMMAND = [[sys.executable, "-c", "raise SystemExit(0)"]]


def initialize_repository(workspace: Path) -> None:
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    (workspace / "README.md").write_text("# Example\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git", "-C", str(workspace),
            "-c", "user.name=Test",
            "-c", "user.email=test@example.com",
            "commit", "-q", "-m", "initial project",
        ],
        check=True,
    )


class LifecycleLockHygieneTests(unittest.TestCase):
    def make_session(self, workspace: Path) -> Path:
        return create_session(
            workspace,
            "lifecycle-lock",
            ["README.md"],
            PASS_COMMAND,
            expected_outputs=["README.md"],
        )

    def test_close_allows_lifecycle_lock_at_process_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            lock_path = workspace / ".run/paperclip/.lifecycle.lock"
            lock_path.write_text("", encoding="utf-8")
            (session / "todo.md").write_text("# Process TODO\n\n- [x] Done.\n", encoding="utf-8")

            result = close_session(workspace, session.name)

            self.assertEqual("allow", result["decision"])
            self.assertTrue(result["closed"])

    def test_other_process_root_entries_remain_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            initialize_repository(workspace)
            session = self.make_session(workspace)
            process_root = workspace / ".run/paperclip"
            (process_root / "unexpected.lock").write_text("", encoding="utf-8")
            (process_root / ".lifecycle.lock").mkdir()

            result = analyze(workspace, selected_session=session.name)
            root_entry_paths = {
                finding["path"]
                for finding in result["findings"]
                if finding["code"] == "process.root_entry"
            }

            self.assertEqual(
                {".run/paperclip/.lifecycle.lock", ".run/paperclip/unexpected.lock"},
                root_entry_paths,
            )


if __name__ == "__main__":
    unittest.main()
