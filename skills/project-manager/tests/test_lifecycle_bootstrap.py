import tempfile
import unittest
from pathlib import Path

from scripts.artifact_consistency_checker import analyze_feature
from scripts.release_record_bootstrap import bootstrap_release


class LifecycleBootstrapTests(unittest.TestCase):
    def test_intake_does_not_require_future_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            prd = workspace / "docs/product/payment/001-overview.md"
            prd.parent.mkdir(parents=True)
            prd.write_text("# PRD\n", encoding="utf-8")
            report = analyze_feature(workspace, "payment", "intake")
            self.assertEqual("allow", report["normalized_decision"])
            self.assertFalse(any("测试报告" in item["title"] for item in report["findings"]))

    def test_release_record_bootstrap_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target, first = bootstrap_release(workspace, "2026-07-12", "WAR-346", "Payment Release")
            repeated, second = bootstrap_release(workspace, "2026-07-12", "WAR-346", "Payment Release")
            self.assertEqual("written", first)
            self.assertEqual("skipped", second)
            self.assertEqual(target, repeated)
            self.assertTrue((target / "001-overview.md").exists())
            self.assertIn("WAR-346", "\n".join(path.read_text(encoding="utf-8") for path in target.glob("*.md")))

    def test_release_record_requires_canonical_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                bootstrap_release(Path(temp_dir), "2026-07-12", "release", "payment")


if __name__ == "__main__":
    unittest.main()
