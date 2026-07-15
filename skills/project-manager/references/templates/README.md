# Templates

`templates/` 保存标准文档模板，供具体功能文档直接复用。

适合放在这里的内容：

- PRD 模板
- UI 设计交接模板
- 架构与技术设计模板
- 测试用例模板
- 复盘模板
- 发布记录模板
- 测试报告模板
- 项目状态台账模板

当前文件：

- [PRD Template](prd-template.md)
- [UI Design Template](ui-design-template.md)
- [Architecture Design Template](architecture-design-template.md)
- [Test Case Template](test-case-template.md)
- [Retrospective Template](retrospective-template.md)
- [Release Record Template](release-record-template.md)
- [Test Report Template](test-report-template.md)
- [Project Status Template](project-status-template.yaml)

这些文件是文档包的聚合模板源。`feature-doc-bootstrap` 和 `release-record-bootstrap` 会按二级标题拆成 `001-overview.md`、`002-...md` 等连续编号章节，并在总览中生成章节目录；业务仓库不应复制成单一大文件。
