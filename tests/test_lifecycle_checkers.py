import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts.lifecycle_checkers import analyze_openapi, analyze_project_status, analyze_retrospective, analyze_test_report


class LifecycleCheckerTests(unittest.TestCase):
    def test_openapi_requires_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openapi.yaml"
            path.write_text("openapi: 3.1.0\ninfo: {title: API, version: 1.0.0}\npaths: {}\n", encoding="utf-8")
            self.assertEqual("block", analyze_openapi(path)["normalized_decision"])
            path.write_text("openapi: 3.1.0\ninfo: {title: API, version: 1.0.0}\npaths: {'/health': {get: {responses: {'200': {description: OK}}}}}\n", encoding="utf-8")
            self.assertEqual("allow", analyze_openapi(path)["normalized_decision"])

    def test_openapi_detects_broken_refs_and_removed_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline.yaml"
            current = root / "openapi.yaml"
            baseline.write_text("openapi: 3.1.0\ninfo: {title: API, version: 1}\npaths: {'/users': {get: {responses: {'200': {description: OK}}}}}\n", encoding="utf-8")
            current.write_text("openapi: 3.1.0\ninfo: {title: API, version: 2}\npaths: {'/health': {get: {responses: {'200': {description: OK, content: {application/json: {schema: {$ref: '#/components/schemas/Missing'}}}}}}}}\n", encoding="utf-8")
            result = analyze_openapi(current, baseline)
            codes = {item["code"] for item in result["findings"]}
            self.assertIn("openapi.refs", codes)
            self.assertIn("openapi.breaking.removed", codes)

    def test_project_status_detects_overdue_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.yaml"
            overdue = date.today() - timedelta(days=1)
            path.write_text(f"project: demo\nowner: pm\nmilestones: [{{name: M1}}]\nrisks:\n  - risk: delay\n    impact: release\n    owner: pm\n    action: recover\n    due: {overdue}\n    status: open\n", encoding="utf-8")
            self.assertEqual("block", analyze_project_status(path)["normalized_decision"])

    def test_project_status_accepts_complete_future_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.yaml"
            future = date.today() + timedelta(days=30)
            path.write_text(f"project: demo\nowner: pm\nmilestones:\n  - name: M1\n    owner: pm\n    due: {future}\n    status: in_progress\nrisks: []\n", encoding="utf-8")
            self.assertEqual("allow", analyze_project_status(path)["normalized_decision"])

    def test_placeholder_test_report_and_retro_are_not_ready(self) -> None:
        root = Path(__file__).resolve().parent.parent / "references/templates"
        self.assertEqual("block", analyze_test_report(root / "test-report-template.md")["normalized_decision"])
        self.assertEqual("revise", analyze_retrospective(root / "retrospective-template.md")["normalized_decision"])


if __name__ == "__main__":
    unittest.main()
