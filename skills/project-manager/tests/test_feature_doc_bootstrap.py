import tempfile
import unittest
from pathlib import Path

from scripts.document_bundle import document_slug, read_document
from scripts.feature_doc_bootstrap import bootstrap, ensure_ascii_slug


class FeatureDocBootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_numbered_bundles_and_feature_openapi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "payment-confirmation", "WAR-342", overwrite=False)

            prd = workspace / "docs/product/payment-confirmation"
            openapi = workspace / "docs/development/payment-confirmation/openapi/001-openapi.yaml"
            self.assertTrue((prd / "001-overview.md").exists())
            self.assertIn("payment-confirmation", read_document(prd))
            self.assertIn("title: payment-confirmation", openapi.read_text(encoding="utf-8"))
            self.assertTrue((workspace / "docs/design/payment-confirmation/pages/001-overview.md").exists())
            self.assertTrue((workspace / "docs/design/payment-confirmation/flows/001-overview.md").exists())
            self.assertTrue((workspace / "docs/design/payment-confirmation/states/001-overview.md").exists())
            numbers = [path.name[:3] for path in sorted(prd.glob("*.md"))]
            self.assertEqual([f"{index:03d}" for index in range(1, len(numbers) + 1)], numbers)

    def test_overwrite_preserves_feature_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "feature-one", None, overwrite=False)
            openapi = workspace / "docs/development/feature-one/openapi/001-openapi.yaml"
            openapi.write_text("openapi: 3.1.0\ninfo:\n  title: canonical\n", encoding="utf-8")

            bootstrap(workspace, "feature-one", None, overwrite=True)

            self.assertIn("title: canonical", openapi.read_text(encoding="utf-8"))

    def test_slug_normalization(self) -> None:
        self.assertEqual("payment-confirmation", ensure_ascii_slug("Payment Confirmation"))
        with self.assertRaises(ValueError):
            ensure_ascii_slug("支付确认")

    def test_nested_test_bundle_has_feature_scoped_slug(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "docs/testing/payment/test-cases"
            path.mkdir(parents=True)
            self.assertEqual("payment-test-cases", document_slug(path))

    def test_bootstrap_rejects_parallel_legacy_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            legacy = workspace / "docs/product/payment.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# 旧 PRD\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "旧版扁平文档"):
                bootstrap(workspace, "payment", None, overwrite=False)


if __name__ == "__main__":
    unittest.main()
