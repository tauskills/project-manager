# 项目文档总分式目录规范

## 基本规则

- 按功能或发布事件建立独立文档包目录，不在生命周期区域下直接创建单一大文件。
- 每个文档包必须以 `001-overview.md` 作为总览和目录；其余章节按阅读顺序使用连续三位编号，例如 `002-background.md`、`003-scope.md`。
- 文件名格式固定为 `NNN-kebab-case.md`。编号从 `001` 开始，同一目录不得重复或跳号。
- 总览记录 Owner、状态、关联 issue、章节目录和跨阶段路径；分文件只负责一个清晰主题。
- 新增章节时优先追加编号。需要调整顺序时，同一变更中更新文件名、总览目录和所有引用。
- 图片、设计源文件、OpenAPI、Schema 等非章节资产放入明确的子目录；资产可使用自身格式，但不得代替总览和章节。

## 标准目录

```text
docs/
├── product/<feature-slug>/
│   ├── 001-overview.md
│   ├── 002-change-log.md
│   ├── 003-basic-info.md
│   └── ...
├── design/<feature-slug>/
│   ├── 001-overview.md
│   ├── 002-change-log.md
│   ├── ...
│   ├── pages/001-overview.md
│   ├── flows/001-overview.md
│   ├── states/001-overview.md
│   ├── assets/design-source.fig
│   ├── screens/
│   └── exports/
├── development/<feature-slug>/
│   ├── 001-overview.md
│   ├── 002-basic-info.md
│   ├── ...
│   ├── openapi/001-openapi.yaml
│   ├── schema/001-schema.sql
│   └── notes/001-overview.md
├── testing/<feature-slug>/
│   ├── 001-overview.md
│   ├── test-cases/001-overview.md
│   └── test-report/
│       ├── 001-overview.md
│       └── evidence/<date>-<slug>/
│           ├── 001-overview.md
│           ├── screenshots/
│           ├── logs/
│           └── attachments/
├── retrospective/<feature-slug>/
│   ├── 001-overview.md
│   └── ...
└── release/<date>-<issue-key>-<slug>/
    ├── 001-overview.md
    └── ...
```

## 模块约束

### PRD

把背景、目标、用户场景、范围、流程、异常、非功能约束、验收标准和风险拆成独立章节。`001-overview.md` 只承担入口、目录和整体状态，不把所有正文重新复制一遍。

### UI 设计

根目录编号文件描述整体交接。`pages/` 按页面拆分，`flows/` 按跨页面流程拆分，`states/` 描述加载、空态、错误、权限和边界状态。每个子目录同样从 `001-overview.md` 开始。源文件、截图和导出资源分别进入 `assets/`、`screens/` 和 `exports/`。

### 架构与开发

把系统边界、技术选型、实现策略、接口与数据变更、风险、测试发布回滚拆开。OpenAPI 和 Schema 归属于功能目录；开发过程记录放在 `notes/`，不得散落成同级临时文件。

### 测试、发布与复盘

测试功能目录提供总览，再分别维护 `test-cases/` 和 `test-report/` 文档包。每次发布使用事件目录，发布范围、门禁、步骤、回滚、监控和结果各自成章。复盘按功能建立目录，将时间线、根因、改进动作和结论分章维护。

测试原始证据归属于对应功能的测试报告，放入 `test-report/evidence/<date>-<slug>/`。证据集以 `001-overview.md` 建立报告引用、采集环境、时间、执行者角色、文件清单、脱敏检查和可达性结论；截图放 `screenshots/`，浏览器网络、控制台、运行和命令输出的脱敏摘要放 `logs/`，其他可文本复核的结构化结果放 `attachments/`。截图命名为 `NNN-{before|after|error|verification}-<surface-slug>.<png|jpg|jpeg|webp>`；日志命名为 `NNN-{browser-console|browser-network|runtime|command}-summary.<txt|json|csv|xml>`；附件命名为 `NNN-<artifact-slug>.<txt|json|csv|xml>`。

不得归档原始 HAR、完整响应体、cookie、token、密码、测试账号、邮箱、手机号或其他 PII。先最小化并脱敏，再写入证据集；无法证明脱敏或无法从报告稳定到达的文件不能作为发布门禁证据。历史散落证据迁移时先建立证据集索引，再按类型和三位序号重命名，更新报告引用，最后删除旧路径；不得让新旧 canonical path 长期并存。

## 旧结构迁移

把旧的 `docs/product/<feature>.md` 等扁平文件迁入对应功能目录，并按二级标题拆分为连续编号文件。完成迁移后更新所有交叉引用，再删除旧文件；不得长期并存两套 canonical path。
