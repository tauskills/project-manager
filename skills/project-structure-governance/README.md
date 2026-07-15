# Project Structure Governance

用于初始化和检查软件仓库目录结构的 Codex skill。支持单应用、多应用、技术 Profile、文档命名和根目录治理。

## 功能

- 根据技术栈创建标准目录和 `.project-structure.json`。
- 将多应用隔离到 `apps/<name>/`，共享代码放入 `packages/`。
- 自动维护 `docs/project/project-overview.md` 的应用清单。
- 检查未登记目录、命名错误、敏感文件和结构冲突。
- 按功能或发布事件检查总分式文档目录和三位章节编号。

## 快速开始

单应用：

```bash
python3 scripts/project_structure_bootstrap.py \
  --workspace /path/to/project \
  --profile go
```

多应用：

```bash
python3 scripts/project_structure_bootstrap.py \
  --workspace /path/to/project \
  --application web=node \
  --application api=go
```

检查仓库：

```bash
python3 scripts/project_structure_checker.py \
  --workspace /path/to/project \
  --fail-on revise
```

使用 `--dry-run` 预览初始化结果；旧版 manifest 使用 `--migrate` 显式升级。

## 文档

- [Skill 使用说明](SKILL.md)
- [项目结构规范](references/project-structure-standard.md)
- [项目文档总分式目录规范](references/document-bundle-standard.md)
- [Manifest Schema](references/project-manifest.schema.json)
