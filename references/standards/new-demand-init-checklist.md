# 新需求初始化清单

适用场景：项目管理工程师在新需求立项后，用这份清单先判断是否属于既有功能迭代，再决定是复用原文档还是初始化新功能文档，避免跨角色直接口头推进。

## 0. 先判断是否复用既有功能文档

立项时先执行：

1. 检查 `docs/product/`、`docs/design/`、`docs/development/`、`docs/testing/`、`docs/retrospective/` 下是否已存在该功能对应的 `feature-slug` 文件。
2. 如果新需求只是既有功能的增强、优化、修复或范围补充，直接更新原功能文档。
3. 在原文档追加一条更新记录，至少包含日期、issue、作者、变更摘要。
4. 只有当该功能在仓库内还没有 canonical 文档时，才创建新的功能文档。

## 1. 目录初始化

确认业务仓库中存在以下目录：

- `docs/product/`
- `docs/design/`
- `docs/development/`
- `docs/development/openapi/`
- `docs/development/schema/`
- `docs/testing/`
- `docs/retrospective/`
- `docs/release/`
- `docs/review/prd-qa/`
- `docs/review/ui-design/`
- `docs/review/test-case/`
- `docs/review/architecture-design/`
- `docs/review/artifact-consistency/`
- `docs/review/feature-governance/`
- `docs/review/release-readiness/`

## 2. 文档骨架初始化

若确认是新功能，再按固定命名创建以下文件：

- `docs/product/{feature-slug}.md`
- `docs/design/{feature-slug}.md`
- `docs/design/{feature-slug}.fig`
- `docs/design/{feature-slug}/`
- `docs/design/{feature-slug}/screens/`
- `docs/design/{feature-slug}/assets/`
- `docs/design/{feature-slug}/exports/`
- `docs/development/{feature-slug}.md`
- `docs/development/openapi/openapi.yaml`
- `docs/development/schema/{feature-slug}.sql`
- `docs/testing/{feature-slug}-test-cases.md`
- `docs/release/{date}-{issue-key}-{slug}.md`
- `docs/retrospective/{feature-slug}-retro.md`

## 3. 角色交接初始化

首次 issue 评论至少明确：

- 产品负责人
- UI 负责人
- 架构/技术 Owner
- 前端负责人
- 后端负责人
- 测试负责人
- 发布负责人
- 项目管理负责人

## 4. 门禁准备

进入开发前必须完成：

1. PRD 已更新到功能主文档并通过 `prd-qa-checker`
2. UI 设计已按模板更新到功能主文档，本地设计源文件已保存为 `docs/design/{feature-slug}.fig`，且页面截图已保存到 `docs/design/{feature-slug}/`
3. 架构与技术设计文档已在功能主文档中按模板补齐
4. `openapi.yaml` 更新完成
5. `schema` 脚本更新完成
6. 测试用例已按模板更新到功能主文档
7. 架构与技术设计文档通过 `architecture-design-checker`
8. 发布后按模板补齐功能复盘文档

## 5. 推荐命令

```bash
python3 scripts/feature_doc_bootstrap.py \
  --workspace /path/to/business-repo \
  --feature {feature-slug} \
  --issue {issue-key}

python3 scripts/prd_qa_checker.py \
  --prd docs/product/{feature-slug}.md \
  --issue {issue-key} \
  --output auto

python3 scripts/ui_design_checker.py \
  --ui docs/design/{feature-slug}.md \
  --issue {issue-key} \
  --output auto

python3 scripts/test_case_checker.py \
  --testcase docs/testing/{feature-slug}-test-cases.md \
  --issue {issue-key} \
  --output auto

python3 scripts/architecture_design_checker.py \
  --design docs/development/{feature-slug}.md \
  --issue {issue-key} \
  --output auto

python3 scripts/artifact_consistency_checker.py \
  --workspace /path/to/business-repo \
  --feature {feature-slug} \
  --stage development \
  --issue {issue-key}

python3 scripts/feature_governance_check.py \
  --workspace /path/to/business-repo \
  --feature {feature-slug} \
  --stage development \
  --issue {issue-key}

python3 scripts/release_record_bootstrap.py \
  --workspace /path/to/business-repo \
  --date {release-date} \
  --issue {issue-key} \
  --slug {release-slug}
```
