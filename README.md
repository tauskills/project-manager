# project-manager

项目治理自动化 skill 仓库。

当前包含：

- `prd-qa-checker`
- `release-readiness-checker`
- `project-development-standard`

两个 checker 都输出统一决策码，便于 issue 自动化和上层 agent 复用：

- `allow`
- `revise`
- `block`

主入口见 [`SKILL.md`](SKILL.md)。

推荐在业务仓库内使用以下固定目录：

- `docs/01-product/`：PRD/需求文档
- `docs/02-design/`：UI 设计交接
- `docs/03-development/`：技术方案、OpenAPI、schema
- `docs/04-testing/`：测试用例和测试报告
- `docs/05-retrospective/`：复盘
- `docs/product/`：PRD 原文
- `docs/release/`：发布记录
- `docs/review/prd-qa/`：PRD 检查输出
- `docs/review/release-readiness/`：发布检查输出

项目开发规范见 [`references/project-development-standard.md`](references/project-development-standard.md)，包含需求、UI、架构、开发、测试、发布和复盘的流程图、owner、固定产物路径和 issue 评论契约。

推荐命令：

```bash
python3 scripts/prd_qa_checker.py \
  --prd docs/product/example.md \
  --issue WAR-342 \
  --output auto

python3 scripts/release_readiness_checker.py \
  --release docs/release/example.md \
  --issue WAR-346 \
  --output auto
```
