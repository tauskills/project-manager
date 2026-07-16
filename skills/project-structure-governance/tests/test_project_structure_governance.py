import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_structure_bootstrap import (
    bootstrap,
    detect_applications,
    detect_profiles,
    load_layout,
    parse_application_specs,
)
from scripts.project_structure_checker import analyze, pattern_to_regex, render_text


class ProjectStructureGovernanceTests(unittest.TestCase):
    def test_bootstrap_creates_v3_manifest_profile_zones_and_overview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            results = bootstrap(workspace, "go")

            self.assertTrue((workspace / "cmd").is_dir())
            self.assertTrue((workspace / "internal").is_dir())
            self.assertTrue((workspace / "scripts").is_dir())
            self.assertTrue((workspace / "docs/project/project-overview.md").is_file())
            self.assertTrue((workspace / ".gitignore").is_file())
            manifest = json.loads((workspace / ".project-structure.json").read_text())
            self.assertEqual(3, manifest["version"])
            self.assertEqual(["go"], manifest["profiles"])
            self.assertEqual([], manifest["applications"])
            self.assertIn(("go", "profiles"), results)

    def test_bootstrap_is_idempotent_and_preserves_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            overview = workspace / "docs/project/project-overview.md"
            overview.write_text("# 自定义项目说明\n", encoding="utf-8")
            second = bootstrap(workspace, "generic")

            self.assertIn((".project-structure.json", "skipped"), second)
            self.assertIn((".gitignore", "skipped"), second)
            content = overview.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 自定义项目说明\n"))
            self.assertIn("| 无（单应用仓库） |", content)

    def test_bootstrap_rejects_conflicts_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            conflict = workspace / "docs/project/project-overview.md"
            conflict.mkdir(parents=True)
            with self.assertRaises(ValueError):
                bootstrap(workspace, "generic")
            self.assertFalse((workspace / ".project-structure.json").exists())
            self.assertFalse((workspace / "src").exists())

    def test_bootstrap_dry_run_does_not_create_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "new-repository"
            results = bootstrap(workspace, "generic", dry_run=True)
            self.assertFalse(workspace.exists())
            self.assertIn((".project-structure.json", "planned-written"), results)

    def test_bootstrap_migrates_v1_manifest_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            manifest_path = workspace / ".project-structure.json"
            manifest_path.write_text(json.dumps({
                "version": 1, "profile": "node", "additional_zones": [], "allowed_root_files": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--migrate"):
                bootstrap(workspace)

            bootstrap(workspace, migrate=True)
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(3, manifest["version"])
            self.assertEqual(["node"], manifest["profiles"])
            self.assertEqual([], manifest["applications"])
            self.assertNotIn("profile", manifest)

    def test_bootstrap_migrates_v2_manifest_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            manifest_path = workspace / ".project-structure.json"
            manifest_path.write_text(json.dumps({
                "version": 2,
                "profiles": ["go"],
                "additional_zones": [],
                "allowed_root_files": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--migrate"):
                bootstrap(workspace)
            bootstrap(workspace, migrate=True)
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(3, manifest["version"])
            self.assertEqual([], manifest["applications"])

    def test_auto_detects_multiple_profiles_from_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text("{}\n", encoding="utf-8")
            (workspace / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            self.assertEqual(["monorepo"], detect_profiles(workspace, load_layout()))

    def test_auto_detects_existing_applications_and_their_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "apps/web").mkdir(parents=True)
            (workspace / "apps/web/package.json").write_text("{}\n", encoding="utf-8")
            (workspace / "apps/api").mkdir()
            (workspace / "apps/api/go.mod").write_text("module example.test/api\n", encoding="utf-8")

            applications = detect_applications(workspace, load_layout())
            self.assertEqual(["api", "web"], [item["name"] for item in applications])
            bootstrap(workspace)
            manifest = json.loads((workspace / ".project-structure.json").read_text())
            self.assertEqual(["monorepo"], manifest["profiles"])
            self.assertEqual(applications, manifest["applications"])
            self.assertTrue((workspace / "apps/web/src").is_dir())
            self.assertTrue((workspace / "apps/api/internal").is_dir())

    def test_checker_allows_single_root_multi_profile_repository_and_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, ["node", "go"])
            (workspace / "package.json").write_text("{}\n", encoding="utf-8")
            (workspace / "go.mod").write_text("module example.test/project\n", encoding="utf-8")
            (workspace / "tsconfig.app.json").write_text("{}\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("allow", report["decision"])
            self.assertEqual(["node", "go"], report["profiles"])
            self.assertEqual([], report["applications"])
            self.assertIn("profiles: node,go", render_text(report))

    def test_bootstrap_creates_isolated_multi_application_structure_and_table(self) -> None:
        applications = [
            {
                "name": "web",
                "path": "apps/web",
                "profiles": ["node"],
                "owner": "frontend-team",
                "purpose": "Customer web application",
            },
            {
                "name": "api",
                "path": "apps/api",
                "profiles": ["go"],
                "owner": "backend-team",
                "purpose": "Service API",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, applications=applications)

            self.assertTrue((workspace / "apps/web/src").is_dir())
            self.assertTrue((workspace / "apps/api/cmd").is_dir())
            self.assertTrue((workspace / "apps/api/internal").is_dir())
            self.assertFalse((workspace / "src").exists())
            self.assertFalse((workspace / "cmd").exists())
            manifest = json.loads((workspace / ".project-structure.json").read_text())
            self.assertEqual(["monorepo"], manifest["profiles"])
            self.assertEqual(applications, manifest["applications"])
            overview = (workspace / "docs/project/project-overview.md").read_text(encoding="utf-8")
            self.assertIn("| web | `apps/web` | node | frontend-team | Customer web application |", overview)
            self.assertIn("| api | `apps/api` | go | backend-team | Service API |", overview)
            self.assertEqual("allow", analyze(workspace)["decision"])

    def test_bootstrap_synchronizes_overview_after_manifest_application_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            applications = parse_application_specs(["web=node", "api=go"])
            bootstrap(workspace, applications=applications)
            manifest_path = workspace / ".project-structure.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["applications"][0]["owner"] = "experience-team"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            stale_report = analyze(workspace)
            self.assertEqual("revise", stale_report["decision"])
            self.assertIn("overview.applications", {item["code"] for item in stale_report["findings"]})
            bootstrap(workspace, applications=parse_application_specs(["web=node", "api=go"]))
            overview = (workspace / "docs/project/project-overview.md").read_text(encoding="utf-8")
            self.assertIn("experience-team", overview)
            self.assertEqual("allow", analyze(workspace)["decision"])

    def test_checker_blocks_missing_registered_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, applications=parse_application_specs(["web=node"]))
            (workspace / "apps/web/src").rmdir()
            (workspace / "apps/web").rmdir()
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("application.missing", {item["code"] for item in report["findings"]})

    def test_checker_blocks_missing_application_profile_zone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, applications=parse_application_specs(["web=node"]))
            (workspace / "apps/web/src").rmdir()
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("application.zone_missing", {item["code"] for item in report["findings"]})

    def test_checker_reports_application_missing_from_manifest_and_overview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, applications=parse_application_specs(["web=node"]))
            (workspace / "apps/worker").mkdir()
            report = analyze(workspace)
            self.assertEqual("revise", report["decision"])
            self.assertIn("application.unregistered", {item["code"] for item in report["findings"]})

    def test_application_spec_parser_rejects_invalid_input(self) -> None:
        self.assertEqual(["node", "go"], parse_application_specs(["gateway=node,go"])[0]["profiles"])
        with self.assertRaises(ValueError):
            parse_application_specs(["gateway"])

    def test_checker_reports_unowned_top_level_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            (workspace / "misc").mkdir()
            (workspace / "notes.txt").write_text("temporary\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("revise", report["decision"])
            self.assertEqual(
                {"zone.unowned", "root_file.unowned"},
                {item["code"] for item in report["findings"]},
            )

    def test_checker_blocks_prohibited_root_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            (workspace / ".env.production").write_text("TOKEN=secret\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("root_file.prohibited", {item["code"] for item in report["findings"]})

    def test_manifest_cannot_override_prohibited_root_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            manifest_path = workspace / ".project-structure.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["allowed_root_files"] = ["credentials.json"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (workspace / "credentials.json").write_text("{}\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("root_file.prohibited", {item["code"] for item in report["findings"]})

    def test_checker_blocks_root_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            (workspace / "linked-source").symlink_to(workspace / "src", target_is_directory=True)
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("root_entry.symlink", {item["code"] for item in report["findings"]})

    def test_checker_allows_manifest_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "python")
            manifest_path = workspace / ".project-structure.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["additional_zones"] = [{
                "path": "migrations", "owner": "engineering", "purpose": "Database migrations",
            }]
            manifest["allowed_root_files"] = ["alembic.ini"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (workspace / "migrations").mkdir()
            (workspace / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            self.assertEqual("allow", analyze(workspace)["decision"])

    def test_checker_rejects_invalid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            manifest_path = workspace / ".project-structure.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["additional_zones"] = [{"path": "../shared", "owner": "x", "purpose": "x"}]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("manifest.invalid", {item["code"] for item in report["findings"]})

    def test_checker_blocks_legacy_manifest_with_migration_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            (workspace / ".project-structure.json").write_text(json.dumps({
                "version": 1, "profile": "generic", "additional_zones": [], "allowed_root_files": [],
            }), encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("block", report["decision"])
            self.assertIn("manifest.version", {item["code"] for item in report["findings"]})

    def test_checker_enforces_kebab_case_in_non_code_zones(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "node")
            (workspace / "assets/Hero Image.png").write_bytes(b"image")
            report = analyze(workspace)
            self.assertEqual("revise", report["decision"])
            self.assertIn("naming.noncanonical", {item["code"] for item in report["findings"]})

    def test_checker_enforces_document_slug_and_language_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            (workspace / "docs/product/Not A Slug").mkdir()
            (workspace / "docs/product/Not A Slug/001-overview.md").write_text("# 中文\n", encoding="utf-8")
            (workspace / "docs/product/payment").mkdir()
            (workspace / "docs/product/payment/001-overview.md").write_text("# Payment\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual(
                {"document.noncanonical", "document.language_baseline"},
                {item["code"] for item in report["findings"]},
            )

    def test_checker_allows_numbered_document_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            bundle = workspace / "docs/product/payment"
            bundle.mkdir()
            (bundle / "001-overview.md").write_text("# 支付功能总览\n\n## 章节目录\n\n- [背景](002-background.md)\n", encoding="utf-8")
            (bundle / "002-background.md").write_text("## 背景\n\n支付需求。\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertEqual("allow", report["decision"])
            self.assertIn("文档包编号有效：docs/product/payment", report["passes"])

    def test_checker_allows_project_governance_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            governance = workspace / "docs/project/project-governance"
            governance.mkdir()
            chapters = [
                "001-overview.md",
                "002-project-conventions.md",
                "003-roadmap.md",
                "004-feature-artifact-index.md",
                "005-docs-output-inventory.md",
                "006-design-coverage-audit.md",
                "007-document-language-governance.md",
                "008-file-organization-policy.md",
                "009-application-directory-naming-decision.md",
                "010-governance-change-log.md",
            ]
            for chapter in chapters:
                (governance / chapter).write_text("# 项目治理\n", encoding="utf-8")

            report = analyze(workspace)

            noncanonical = [
                item["path"]
                for item in report["findings"]
                if item["code"] == "document.noncanonical"
            ]
            self.assertEqual([], noncanonical)

    def test_checker_allows_redacted_test_report_evidence_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            report_bundle = workspace / "docs/testing/payment/test-report"
            evidence_bundle = report_bundle / "evidence/2026-07-16-checkout-regression"
            (evidence_bundle / "screenshots").mkdir(parents=True)
            (evidence_bundle / "logs").mkdir()
            (evidence_bundle / "attachments").mkdir()
            (workspace / "docs/testing/payment/001-overview.md").write_text("# 支付测试总览\n", encoding="utf-8")
            report_bundle.mkdir(parents=True, exist_ok=True)
            (report_bundle / "001-overview.md").write_text("# 支付测试报告\n", encoding="utf-8")
            (evidence_bundle / "001-overview.md").write_text("# 证据索引\n\n已完成脱敏检查。\n", encoding="utf-8")
            (evidence_bundle / "screenshots/001-verification-checkout-desktop.png").write_bytes(b"image")
            (evidence_bundle / "logs/002-browser-network-summary.txt").write_text("GET /checkout 200\n", encoding="utf-8")
            (evidence_bundle / "attachments/003-test-results.json").write_text("{}\n", encoding="utf-8")

            report = analyze(workspace)

            self.assertNotIn("document.noncanonical", {item["code"] for item in report["findings"]})

    def test_checker_rejects_unindexed_or_raw_test_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            raw_evidence = workspace / "docs/testing/payment/test-report/evidence/checkout-regression"
            raw_evidence.mkdir(parents=True)
            (raw_evidence / "session.har").write_text("{}\n", encoding="utf-8")

            report = analyze(workspace)

            findings = [item for item in report["findings"] if item["code"] == "document.noncanonical"]
            self.assertEqual(["docs/testing/payment/test-report/evidence/checkout-regression/session.har"], [item["path"] for item in findings])

    def test_checker_blocks_missing_overview_and_invalid_chapter_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            bundle = workspace / "docs/product/payment"
            bundle.mkdir()
            (bundle / "1-background.md").write_text("# 背景\n", encoding="utf-8")
            report = analyze(workspace)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("document.chapter_name", codes)

    def test_checker_reports_non_contiguous_chapter_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            bootstrap(workspace, "generic")
            bundle = workspace / "docs/product/payment"
            bundle.mkdir()
            (bundle / "001-overview.md").write_text("# 总览\n", encoding="utf-8")
            (bundle / "003-scope.md").write_text("# 范围\n", encoding="utf-8")
            report = analyze(workspace)
            self.assertIn("document.chapter_sequence", {item["code"] for item in report["findings"]})

    def test_checker_blocks_without_manifest_and_overview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = analyze(Path(temp_dir))
            self.assertEqual("block", report["decision"])
            self.assertEqual(
                {"manifest.missing", "required.missing"},
                {item["code"] for item in report["findings"]},
            )

    def test_pattern_compiler_uses_layout_placeholders(self) -> None:
        regex = pattern_to_regex("docs/release/{date}-{issue-key}-{slug}/{chapter}.md")
        self.assertIsNotNone(regex.fullmatch("docs/release/2026-07-13-TAU-123-fix-login/001-overview.md"))
        with self.assertRaises(ValueError):
            pattern_to_regex("docs/{unknown}.md")


if __name__ == "__main__":
    unittest.main()
