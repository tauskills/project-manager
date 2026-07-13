# tauskills project governance

面向 Codex 的项目治理 Skill 集合，覆盖仓库结构和研发全生命周期门禁。

## Skills

- [`project-manager`](skills/project-manager/SKILL.md)：检查 PRD、设计、技术方案、测试、发布和复盘产物，并聚合生命周期门禁。
- [`project-structure-governance`](skills/project-structure-governance/SKILL.md)：初始化并审计仓库目录、应用边界、文件命名和项目文档布局。

先使用 `project-structure-governance` 建立或检查仓库结构，再使用 `project-manager` 检查各阶段产物质量。

## Validation

```bash
python3 -m pip install -r skills/project-manager/requirements.txt

(cd skills/project-manager && python3 -m unittest discover -s tests -v)
(cd skills/project-structure-governance && python3 -m unittest discover -s tests -v)
```
