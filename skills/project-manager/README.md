# project-manager

项目治理自动化 skill 仓库。

主入口见 [`SKILL.md`](SKILL.md)。

## 能力

当前提供以下治理能力：

- `feature-doc-bootstrap`：初始化功能级文档与设计资产骨架
- `prd-qa-checker`：检查 PRD 是否具备进入设计 / 技术评审条件
- `ui-design-checker`：检查 UI 设计交接是否完整
- `test-case-checker`：检查测试用例是否覆盖需求与异常场景
- `architecture-design-checker`：检查架构与技术设计是否具备开工条件
- `artifact-consistency-checker`：检查 PRD、UI、技术、测试文档之间是否一致
- `feature-governance-check`：汇总功能级治理检查结果
- `release-readiness-checker`：检查发布记录和发布门禁是否就绪
- `release-record-bootstrap`：按标准模板初始化单次发布记录
- `project-development-standard`：定义跨角色流程、生命周期交接和交付约束
- `api-contract-checker`：校验 OpenAPI 结构和接口操作
- `test-report-checker`：检查测试执行证据与结论
- `retrospective-checker`：检查复盘和改进动作闭环
- `project-status-checker`：检查里程碑、风险 Owner 和截止时间

检查器统一输出决策码，便于 issue 自动化和上层 agent 复用：

- `allow`
- `revise`
- `block`

文档组织默认按功能聚合，而不是按每次需求单独拆文档。若新需求只是既有功能的补充、优化或修复，应更新原功能文档，并追加更新记录，而不是再创建一套重复文档。

## 文档管理

项目文档目录、命名、中文内容和仓库归档要求由独立的 `$project-document-governance` skill 统一管理。启动生命周期工作前，先使用该 skill 初始化或检查业务仓库的文档布局；本 skill 只负责各阶段产物的内容质量和门禁。

## 命令

常用命令如下：

```bash
python3 scripts/prd_qa_checker.py \
  --prd docs/product/example.md \
  --issue WAR-342 \
  --output auto

python3 scripts/ui_design_checker.py \
  --ui docs/design/payment-confirmation.md \
  --issue WAR-342 \
  --output auto

python3 scripts/test_case_checker.py \
  --testcase docs/testing/payment-confirmation-test-cases.md \
  --issue WAR-342 \
  --output auto

python3 scripts/artifact_consistency_checker.py \
  --workspace /path/to/business-repo \
  --feature payment-confirmation \
  --issue WAR-342

python3 scripts/feature_governance_check.py \
  --workspace /path/to/business-repo \
  --feature payment-confirmation \
  --issue WAR-342 \
  --stage development \
  --fail-on block

python3 scripts/feature_doc_bootstrap.py \
  --workspace /path/to/business-repo \
  --feature payment-confirmation \
  --issue WAR-342

python3 scripts/architecture_design_checker.py \
  --design docs/development/payment-reconciliation.md \
  --issue WAR-342 \
  --output auto

python3 scripts/release_readiness_checker.py \
  --release docs/release/example.md \
  --issue WAR-346 \
  --output auto

python3 scripts/release_record_bootstrap.py \
  --workspace /path/to/business-repo \
  --date 2026-07-12 \
  --issue WAR-346 \
  --slug payment-release
```

## 参考资料

规范、模板、示例和检查规则集中放在 [`references/`](references/README.md)：

- [Project Development Standard](references/standards/project-development-standard.md)
- [New Demand Init Checklist](references/standards/new-demand-init-checklist.md)
- [PRD Template](references/templates/prd-template.md)
- [UI Design Template](references/templates/ui-design-template.md)
- [Architecture Design Template](references/templates/architecture-design-template.md)
- [Test Case Template](references/templates/test-case-template.md)
- [Retrospective Template](references/templates/retrospective-template.md)
- [References Index](references/README.md)
