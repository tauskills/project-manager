# Paperclip 项目边界规范

## 目录

- [1. 目标与边界](#1-目标与边界)
- [2. 强制规则](#2-强制规则)
- [3. 本地过程区](#3-本地过程区)
- [4. 过程产物规范](#4-过程产物规范)
- [5. 生命周期](#5-生命周期)
- [6. 判定标准](#6-判定标准)

## 1. 目标与边界

Paperclip 只负责分配、执行和交接工作，不成为项目业务模型、正式文档结构或代码命名的一部分。本规范隔离以下两类信息：

- 项目事实：需求、业务规则、领域概念、技术决策、代码行为、测试结果和发布结论。
- Paperclip 执行上下文：task 标题、task ID、task URL、agent 名称或 ID、prompt、指派状态、运行状态、重试记录、中间 TODO、过程截图、日志和临时推理记录。

项目事实可以从 task 中提炼，但必须改写为脱离 Paperclip 仍然成立的表述。执行上下文只能进入本规范定义的本地过程区。

## 2. 强制规则

### 2.1 正式项目资产去耦

以下位置不得包含 Paperclip 执行上下文：

- `docs/` 中的需求、设计、开发、测试、发布、复盘和项目状态文档；
- 源代码、测试代码、注释、配置、数据库迁移、脚本、资源和生成接口；
- 文件名、目录名、包名、模块名、类型名、函数名、变量名、测试名和迁移名；
- 分支名、提交信息、发布说明、构建产物名和项目内链接。

禁止使用 task 标题、task 名称或 task 引用命名上述资产。命名必须描述稳定的领域能力、用户行为、技术职责或决策，例如使用 `payment-timeout-policy.md`，不得使用 `task-1842.md`、`fix-paperclip-task.md` 或 task 标题的机械转写。

不得通过缩写、哈希、拼音、前后缀或隐藏元数据规避本规则。不得把 task 原文整段复制到正式文档后仅删除标题。

项目已经采用的中立需求或缺陷系统编号可以按仓库规则引用；Paperclip 内部 task/agent/run 编号不可作为项目追踪编号。如果 Paperclip task 关联了项目正式 issue，只保留正式 issue 引用。

### 2.2 允许的提炼

可以进入正式项目资产的内容必须同时满足：

1. 内容描述项目本身，而不是 Paperclip 如何执行工作；
2. 删除 task、agent 和 run 信息后仍然完整、可理解、可维护；
3. 已根据现有代码、需求或验证证据确认，不把 prompt 当作事实；
4. 使用项目术语重新组织，不保留“根据任务要求”“agent 已完成”等过程叙述；
5. 放入项目规范定义的唯一目标路径，而不是新建 task 专属文档。

Paperclip task 和 prompt 不得成为项目唯一事实来源。产品要求必须进入项目认可的 PRD、issue 或需求系统；技术决策进入架构文档或 ADR；缺陷和测试结论进入项目正式追踪系统。关闭 Paperclip task 后，项目仍必须能够独立理解变更原因、实现和验证依据。

### 2.3 有意集成 Paperclip 的例外

如果项目产品本身确实集成 Paperclip，可以在明确的产品边界内出现 Paperclip 名称、客户端、协议和配置。该例外只适用于产品行为，不适用于当前开发 task 的标题、ID、agent、prompt 或运行记录。

使用检查器例外时必须指定最小 `--allow-path`。禁止放行仓库根、`src/`、`docs/`、`tests/` 等宽泛路径。例外路径仍需人工检查当前执行上下文泄漏。

## 3. 本地过程区

唯一默认过程根目录为：

```text
.run/paperclip/
├── checkouts/                 # 执行 harness 管理的本地 Git worktree
└── sessions/
    └── 20260715T103000Z-payment-timeout/
        ├── context.json
        ├── todo.md
        ├── handoff.md
        ├── evidence.md
        ├── delivery.json       # close 时生成
        ├── notes/
        ├── screens/
        ├── logs/
        └── scratch/
```

`.run/paperclip/` 必须被 Git 忽略且不得强制入库。项目代码、构建、测试和正式文档不得读取、链接或依赖该目录。不要在仓库其他位置建立第二个 Paperclip 过程目录。

`checkouts/` 是执行 harness 为隔离 Git worktree 保留的运行目录，与 `sessions/` 同为仅允许的过程根目录入口。检查器不将 checkout 内的工作树重复归属给当前 session；每个 checkout 仍应作为独立 workspace 按自身 session 审计。`checkouts/` 必须是本地目录，不得是文件或符号链接；其内容仍必须被 Git 忽略且不得被强制跟踪。

session key 使用 UTC 时间戳和领域 slug：`YYYYMMDDTHHMMSSZ-{domain-slug}`。领域 slug 使用小写 kebab-case，描述稳定能力，不使用 task 标题、task ID、agent 名称、`todo`、`wip`、`temp`、`fix-task` 等过程词。

`context.json` 是唯一允许集中保存 Paperclip task/agent 不透明引用的文件。只保存完成当前运行所需的最少字段，不保存 prompt 全文、访问令牌、cookie、真实环境变量、个人数据或业务秘密。默认 `retention` 为 `discard`。

### 3.1 Session v2 变更契约

创建 session 前仓库必须至少有一个 Git commit。`context.json` v2 必须包含：

| 字段 | 规则 |
| --- | --- |
| `allowed_paths` | agent 可以修改的最小相对路径或 glob；不得使用 `.`、`*` 或 `**` 放行全仓 |
| `forbidden_paths` | 即使属于 allowed 父目录也禁止修改的路径；优先级高于 allowed |
| `expected_outputs` | 关闭时必须存在的具体项目路径，不接受 glob |
| `verification_commands` | 至少一条参数数组；不经过 shell 执行，不得在参数中放密钥 |
| `baseline_head` | session 创建时的 HEAD |
| `baseline_changes` | 创建前已有脏路径的状态和内容指纹 |
| `overlapping_session_keys` | 创建时仍活跃的 peer session key 列表；用于并发归属、关闭与清理门禁，空列表也必须显式记录 |
| `contract_digest` | 上述不可变契约及 session 状态的规范化摘要；不匹配时直接 block |

旧版 v2 context 可能没有 `overlapping_session_keys`。工作阶段检查器将其标记为 `scope.contract_migration_required`，关闭阶段 block；不把缺失字段默认为可信的空列表，也不允许旧 session 为并发改动提供归属证据。使用 `paperclip_session.py migrate --workspace <workspace> --session <session-key>` 在 workspace lifecycle lock 内迁移：工具先把旧 `contract_digest` 保存到 session 的 `scratch/overlap-migration-backup.json`（不复制 task/agent 引用），再保守记录当前过程区内所有合法 peer session key，重算 digest，并原子替换 context。迁移后重新执行 hygiene 检查和原验证命令。

若新版本工具需要回滚，先停止该 workspace 的 create/close/purge 操作，再运行同一命令并追加 `--rollback`。工具只会恢复 digest 有效、确实缺少该字段的迁移前备份；恢复后旧工具可继续读取，当前工具会再次要求迁移。确认迁移稳定并成功关闭 session 前不得删除备份；session 按 retention 正常清理时，备份随过程区一同删除。

检查器比较 baseline HEAD、后续 commit、暂存区和工作区。创建前未变化的用户改动不计入 agent 范围；agent 对这些文件的覆盖、回退、暂存或提交仍视为新变更。执行期间不得修改范围、baseline、验证命令或其摘要；需要扩展范围时关闭或放弃原 session，并用新契约创建 session。多个 session 并存时必须显式传入当前 `--session`；只有当 peer session 的签名契约声明该路径，且该路径在 peer 自身 baseline 之后变化，或该路径是 peer 的具体 `expected_outputs` 且 baseline 指纹与当前内容一致时，才能从当前 session 的越界集合剔除。当前 session 的 allowed 或 forbidden 路径与 peer 重叠时不允许 peer 代为认领；契约损坏或缺失的 peer 也不得作为归属证据。

task 标题只通过 `PAPERCLIP_TASK_TITLE` 或检查器参数在运行时参与相似度检测，不得写入 `context.json`。task/agent 引用可以作为不透明值集中存放，但不得进入正式项目资产。

## 4. 过程产物规范

### 4.1 TODO

`todo.md` 只记录当前 session 的可执行步骤，使用 Markdown checkbox。每项描述一个可验证动作，并在完成后勾选。不得把产品路线图、跨任务 backlog 或长期债务留在此文件；这些内容必须提炼后迁移到项目正式管理系统。

关闭 session 前不得存在未完成的 checkbox。被取消的动作写为已完成并注明 `cancelled:` 及原因，不删除导致风险或范围变化的记录。

### 4.2 Handoff

`handoff.md` 固定包含：

- `Current state`：已验证的当前状态；
- `Evidence`：本 session 内的证据路径或可重复命令；
- `Next action`：下一位 agent 的单一明确入口；
- `Risks`：未解决风险和边界。

不得复制完整 prompt、密钥、认证头、个人数据或大段日志。正式交付文档不得链接 `handoff.md`。

### 4.3 截图与证据

截图只放在 `screens/`，使用：

```text
NNN-{before|after|error|verification}-{surface-slug}.{png|jpg|jpeg|webp}
```

例如：`001-before-checkout-form.png`、`002-verification-checkout-form.png`。编号从 `001` 连续递增；`surface-slug` 描述界面或状态，不使用 task/agent 标识。

每张截图必须在 `evidence.md` 中登记文件、目的、采集时间和脱敏状态。采集前隐藏或裁剪 token、cookie、邮箱、手机号、真实用户数据、内部 URL 参数和无关桌面内容。不得把 Paperclip 控制台截图当作产品证据写入正式设计或测试文档。

### 4.4 Notes、Logs 与 Scratch

- `notes/`：保存短期调查记录；文件名使用三位序号和主题 slug，例如 `001-timeout-observation.md`。
- `logs/`：只保存与当前验证直接相关的最小日志片段；先脱敏，避免整库或无限追加。
- `scratch/`：保存可随时删除的实验代码、导出物和临时转换结果。

过程脚本若需要成为项目能力，必须重写、测试并迁入项目正式脚本目录；不得直接移动 scratch 文件冒充正式实现。

### 4.5 Delivery

`paperclip_session.py close` 生成带摘要校验的 `delivery.json`，只记录变更路径、预期输出存在性、验证命令参数、退出状态、耗时和关闭结论，不保存命令输出、prompt 或推理内容。

关闭门禁要求：全部 TODO 已完成或明确取消；预期输出存在；所有验证命令成功；Git 变更未超出 allowed 且未命中 forbidden；正式资产无 task/agent/run 泄漏；截图、凭据和命名检查通过。

## 5. 生命周期

### 开始

1. 读取仓库结构、命名和贡献规范。
2. 从需求中确定领域能力名称，不复用 task 标题作为文件或代码名。
3. 确定最小 allowed/forbidden 路径、预期输出和验证命令。
4. 在修改项目文件前创建 session 并记录 Git baseline。
5. 确认 `.run/paperclip/` 已忽略且没有被 Git 跟踪。

### 执行

1. 正式改动直接进入项目规范路径，只表达项目事实。
2. TODO、handoff、截图、日志、探索笔记和临时输出留在 session。
3. 从过程区提升内容时重新表述并重新验证，不复制过程元数据。
4. 不在正式资产中建立到 session 的依赖或链接。
5. 使用 `--scan changed` 检查当前 session；提交前使用 `--scan staged` 检查 index 内容。

### 收尾

1. 检查文件名、代码标识符、文档内容、分支/提交信息和 diff。
2. 完成或明确取消全部 TODO，补齐必要证据索引。
3. 使用 `paperclip_session.py close` 执行输出、验证、范围和泄漏门禁并生成 `delivery.json`。
4. `discard` 在成功关闭后自动删除；`external-archive` 提供授权归档引用后关闭，再使用 `purge` 删除本地 session。
5. 关闭失败时修复问题并重试；不得用 `purge --force` 冒充成功交付。
6. 删除后再次检查 Git 状态，确保没有过程文件被跟踪或遗留在正式目录。

## 6. 判定标准

| 判定 | 条件 |
| --- | --- |
| `allow` | 范围、输出和验证契约满足；正式资产无 Paperclip 执行上下文；过程区隔离、忽略且结构合规 |
| `revise` | task 标题相似命名、过程区结构、截图索引、TODO 或其他可修复收尾问题 |
| `block` | 越界/禁区改动、输出或验证失败、task/agent/run 泄漏、过程区被跟踪、敏感信息，或正式实现依赖过程区 |

自动检查不能判断一个看似正常的领域名是否实际由 task 标题机械转写。最终交付前必须人工回答：即使删除 Paperclip 中的 task，这个名称和文档是否仍然是项目自然、长期可维护的一部分？
