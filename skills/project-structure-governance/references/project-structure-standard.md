# 项目结构管理规范

## 核心原则

- 把目录结构视为项目接口。创建文件前先确定产物类型、Owner 和唯一目标区域。
- 仓库级 `.project-structure.json` 是项目实际索引；`project-layout.json` 是跨项目基础索引。
- 把可独立运行、构建或部署的单元视为应用。多应用仓库必须先确定目标应用，再按该应用的 profile 决定代码路径。
- 框架或构建工具要求的原生路径优先，但必须通过 profile 或项目索引显式可见。
- 根目录只存放仓库入口、工具自动发现的清单/配置和法律文件，不存放普通业务实现或临时文件。
- 源文件与生成物分离。不得手工编辑 `dist/`、`build/`、`coverage/` 或 `.run/` 下的内容。
- 密钥和真实环境变量不得入库；只允许提交 `.env.example` 或 `.env.<name>.example`。

## 标准区域

| 区域 | 内容 | 不应存放 |
| --- | --- | --- |
| `apps/<app-name>/` | 可独立运行、构建或部署的应用 | 跨应用共享库、仓库级脚本和文档 |
| `packages/<package-name>/` | 跨应用共享的库、组件、类型和工具 | 独立部署入口、仅单个应用使用的业务实现 |
| profile 源码区 | 单应用仓库的根代码，或某个 `apps/<app-name>/` 内的代码 | 其他应用代码、设计稿、运行日志、发布包 |
| `tests/` | 跨模块、集成、端到端测试 | 产品实现代码 |
| `scripts/` | 安装、开发、CI、发布、维护脚本 | 业务模块、一次性临时脚本 |
| `config/` | 项目拥有的非敏感运行配置 | 工具要求放在根目录的配置、密钥 |
| `assets/` | 不直接对外提供的源资源 | 构建产物、临时导出物 |
| `public/` | 框架直接提供的静态文件 | 需要编译处理的源资源 |
| `docs/` | 需求、设计、接口、测试、发布和复盘资料 | 产品源代码、运行日志 |
| `.github/` | GitHub 工作流、模板和仓库策略 | 通用运维脚本 |

测试在语言或框架明确要求与源码共置时可以共置。应用单元测试和应用内集成测试放在对应 `apps/<app-name>/` 内；跨应用集成测试和仓库级端到端测试放入根 `tests/`。数据库迁移属于某个应用时放在该应用的框架原生目录；只有真正属于整个仓库时才登记为根扩展区域。

## 单应用与多应用

满足以下任一条件的单元视为独立应用：拥有独立启动入口、可以独立构建、可以独立部署，或具有独立运行时生命周期。仅被其他代码引用、不能独立运行的内容属于共享包，不属于应用。

单应用仓库直接在根目录应用技术 profile，例如 Node/Python 使用 `src/`，Go 使用 `cmd/` 和 `internal/`。多应用仓库必须使用根 `monorepo` profile，将每个应用放在 `apps/` 的直接子目录中：

```text
project/
├── apps/
│   ├── web/
│   │   ├── src/
│   │   ├── public/
│   │   └── package.json
│   ├── api/
│   │   ├── cmd/
│   │   ├── internal/
│   │   └── go.mod
│   └── worker/
│       ├── src/
│       └── pyproject.toml
├── packages/
│   ├── design-system/
│   └── shared-contracts/
├── tests/
├── scripts/
├── config/
└── docs/
```

多应用代码落位规则：

- 每个可部署应用必须登记在 `.project-structure.json` 的 `applications` 中，规范路径只能是 `apps/<app-name>`。
- 应用技术 profile 只作用于该应用目录；例如 Go API 使用 `apps/api/cmd/`，不能在仓库根创建 `cmd/`。
- `apps/` 只允许直接放应用，不允许用 `apps/<group>/<app>` 增加未登记层级，也不允许在应用内嵌套另一个 monorepo。
- 应用私有代码、配置、迁移和测试留在该应用内。只有存在两个或更多真实消费者时，代码才迁入 `packages/`。
- `packages/` 下的模块必须使用 kebab-case 命名并明确消费者；不得为了“以后可能复用”提前抽取共享包。
- 根 `scripts/`、`config/`、`tests/` 和 `docs/` 只承载仓库级或跨应用内容，不能成为无法归属到具体应用的暂存区。

应用内部的标准源码路径由 profile 决定：

| 应用 Profile | 应用内源码区域 |
| --- | --- |
| `generic`、`node`、`python`、`java`、`php` | `src/` |
| `go` | `cmd/`、`internal/`，确需公开复用时使用 `pkg/` |
| `rust` | `src/`，基准测试使用 `benches/` |
| `ruby` | `lib/` |
| `flutter` | `lib/`，测试使用 `test/` |

一个应用可以组合多个非 `generic`、非 `monorepo` profile，但必须代表同一部署单元。能够独立部署的前端、API、Worker 或管理后台必须拆成不同 `applications`，不能用组合 profile 掩盖应用边界。

## 命名规则

- 非代码目录、文档名、资源名和项目模块名使用小写 `kebab-case`。
- 代码文件、包、测试和工具配置遵循语言或框架原生命名；不要为了统一外观破坏工具发现规则。
- 脚本扩展名决定命名：Python 模块使用 `snake_case.py`，Shell/可执行命令优先使用 `kebab-case`，框架工具生成的名称保持原样。
- 日期使用 `YYYY-MM-DD`；发布记录 issue key 使用大写项目键加数字，例如 `TAU-123`。
- 禁止 `final-v2`、`new`、`temp`、`misc` 等无法表达 Owner 或生命周期的目录与文件名。

## 项目索引

`.project-structure.json` 最小格式：

```json
{
  "version": 3,
  "profiles": ["monorepo"],
  "applications": [
    {
      "name": "web",
      "path": "apps/web",
      "profiles": ["node"],
      "owner": "frontend-team",
      "purpose": "Customer-facing web application"
    },
    {
      "name": "api",
      "path": "apps/api",
      "profiles": ["go"],
      "owner": "backend-team",
      "purpose": "Public and internal API"
    }
  ],
  "additional_zones": [
    {"path": "migrations", "owner": "engineering", "purpose": "Database migrations"}
  ],
  "allowed_root_files": ["vitest.config.ts"]
}
```

单应用仓库可以在根 `profiles` 组合技术栈；`generic` 只能单独使用。多应用仓库的根 `profiles` 必须是 `monorepo`，每个应用登记在 `applications`，路径固定为 `apps/<name>`，技术 profile 只作用于该应用目录。共享库放入 `packages/<name>`，不要登记为可部署应用。

每个应用必须提供唯一的 kebab-case 名称、profile、Owner 和 Purpose。首次初始化已有仓库时，初始化器会从 `apps/` 的直接子目录及技术标记自动发现应用；新仓库可以通过重复的 `--application name=profile` 参数声明应用。

`.project-structure.json` 是应用清单的唯一权威来源。初始化器会把全部 `applications` 同步到 `docs/project/project-overview.md` 的受管表格；应用的新增、删除、重命名、profile、Owner 或 Purpose 变化都必须反映到该表格。不要手工维护受管标记之间的表格，表格外内容仍由项目维护者编辑。检查器会报告未登记的 `apps/` 子目录、缺失的应用目录、缺失的 profile 源码区以及清单与表格不一致。

扩展区域必须是规范的小写相对路径，不得包含 `..`、空路径段或通配符，并且必须给出 Owner 和 Purpose。`allowed_root_files` 只接受字面文件名；只登记工具确实要求放在根目录的文件，普通配置仍放入 `config/`。完整字段约束见 `project-manifest.schema.json`。

旧版 version 1、2 索引不会被静默改写。使用初始化器的 `--migrate` 参数显式升级；改变已有 profile 或 applications 时同样需要该参数。

## 文档子规范

项目文档和附件必须存放在 `project-layout.json` 的 `document_artifacts` 路径中。在线文档只能作为补充，不能替代仓库归档。项目文档以中文为主；代码标识符、命令、路径、配置字段和常用技术术语可以保留英文。

PRD、UI 设计、开发、测试、发布和复盘必须采用按功能或发布事件聚合的总分式目录。每个文档包以 `001-overview.md` 开始，每个章节独立成文件并使用连续三位编号。具体目录、模块分层和迁移规则见 [项目文档总分式目录规范](document-bundle-standard.md)。

新增通用产物类型时，先更新全局索引和测试。仅当前项目需要的结构写入项目索引，不要扩大所有项目的基础结构。
