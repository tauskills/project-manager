import tempfile
import unittest
from pathlib import Path

from scripts.feature_doc_bootstrap import bootstrap, ensure_ascii_slug


class FeatureDocBootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_templates_and_shared_openapi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "payment-confirmation", "WAR-342", overwrite=False)

            prd = workspace / "docs/product/payment-confirmation.md"
            openapi = workspace / "docs/development/openapi/openapi.yaml"
            self.assertTrue(prd.exists())
            self.assertIn("payment-confirmation", prd.read_text(encoding="utf-8"))
            self.assertIn("title: payment-confirmation", openapi.read_text(encoding="utf-8"))

    def test_overwrite_preserves_project_openapi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "feature-one", None, overwrite=False)
            openapi = workspace / "docs/development/openapi/openapi.yaml"
            openapi.write_text("openapi: 3.1.0\ninfo:\n  title: canonical\n", encoding="utf-8")

            bootstrap(workspace, "feature-two", None, overwrite=True)

            self.assertIn("title: canonical", openapi.read_text(encoding="utf-8"))

    def test_slug_normalization(self) -> None:
        self.assertEqual("payment-confirmation", ensure_ascii_slug("Payment Confirmation"))
        with self.assertRaises(ValueError):
            ensure_ascii_slug("支付确认")


if __name__ == "__main__":
    unittest.main()
