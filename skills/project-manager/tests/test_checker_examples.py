import unittest
from pathlib import Path

from scripts.prd_qa_checker import analyze_prd
from scripts.release_readiness_checker import analyze_release_record


SKILL_ROOT = Path(__file__).resolve().parents[1]


class CheckerExampleTests(unittest.TestCase):
    def test_prd_example_is_allowed(self) -> None:
        markdown = (SKILL_ROOT / "references/examples/prd-example-input.md").read_text(encoding="utf-8")
        report = analyze_prd(markdown)
        self.assertEqual("allow", report["normalized_decision"])
        self.assertEqual("low", report["risk"])

    def test_release_example_is_allowed(self) -> None:
        markdown = (SKILL_ROOT / "references/examples/release-example-input.md").read_text(encoding="utf-8")
        report = analyze_release_record(markdown)
        self.assertEqual("允许发布", report["decision"])
        self.assertEqual("allow", report["normalized_decision"])
        self.assertEqual("low", report["risk"])


if __name__ == "__main__":
    unittest.main()
