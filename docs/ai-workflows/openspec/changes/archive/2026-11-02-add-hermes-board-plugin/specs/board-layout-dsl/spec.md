# 能力规格：看板布局 DSL

状态：已确认（2026-10-31 16:10 用户指示进入计划阶段）。DSL 结构见 [design.md](../../design.md) 第 4 节。

## ADDED Requirements

### Requirement: JSON DSL 结构
系统 MUST 用 JSON 文件 `$HERMES_HOME/plugin-data/hermes-board/board.json` 保存整个看板的布局。顶层字段包括 `schema`（`hermes-board/layout@1`）、`boardId`（v1 固定为 `default`）、`title`、`revision`、`updatedAt`、`updatedBy`、`grid.columns`（v1 固定为 24）和 `items`。每个 `items` 元素包括 `id`、`card`、`x`、`y`、`w`、`h`，单位为格。v1 要求 `id` 等于 `card`。

#### Scenario: 读取布局
- **WHEN** Desktop 请求 `GET /board`。
- **THEN** 返回符合结构的布局文档和卡片注册信息。所有卡片的位置和大小都能从 `items` 直接还原，不依赖本机缓存。

### Requirement: 布局校验
系统 MUST 拒绝不合法的布局写入，包括：坐标或尺寸越界（`x + w > 24`、负数）；`(w,h)` 不在全局预设中或不在该卡片的 `sizes` 中；卡片重叠；`id` 重复；引用了未安装的卡片；超过 64 项；出现未知字段。拒绝时 MUST 返回具体原因，文件内容保持不变。

#### Scenario: 提交重叠布局
- **WHEN** 客户端提交两张卡片矩形相交的布局。
- **THEN** 服务端返回 `invalid` 和重叠的卡片 id，`board.json` 不变。

### Requirement: 原子写入与版本号
系统 MUST 用“临时文件 + fsync + rename”的方式原子写入布局，每次成功写入后 `revision` 加 1，并由服务端填写 `updatedAt` 和 `updatedBy`（`desktop`、`agent`、`system`）。写入后 MUST 追加一条 `layout` 变更，并广播 `plugin.hermes-board.layout.updated`。

#### Scenario: 写入时进程崩溃
- **GIVEN** 写入过程中远程进程意外终止。
- **WHEN** 服务重新启动后读取布局。
- **THEN** 读到的要么是旧版本，要么是新版本的完整文档，不会读到半截文件。

### Requirement: 乐观并发
系统 MUST 要求所有布局修改都带 `baseRevision`。和当前版本不一致时返回 `409` 和当前文档。Desktop 收到冲突后 MUST 在最新文档上重放这一次用户操作并自动重试一次；仍然冲突就以服务端为准刷新，并提示用户。

#### Scenario: Agent 新增卡片的同时用户正在拖动
- **GIVEN** 用户从版本 7 开始拖动卡片，期间 Agent 新增了一张卡片，版本变为 8。
- **WHEN** 用户松手，客户端以 `baseRevision=7` 提交。
- **THEN** 服务端返回 409。客户端在版本 8 上重放这次移动和推挤后重新提交，结果同时包含新卡片和用户的移动。

### Requirement: 不可用卡片的占位
系统 MUST 在布局引用的卡片包缺失或校验失败时保留它在布局中的占位，并在卡片注册信息里标记 `status` 和错误原因，MUST NOT 静默删除这一项。

#### Scenario: 卡片包被手动删除
- **GIVEN** 布局中有 `todo`，但远程的 `cards/todo/` 已被删除。
- **WHEN** Desktop 加载看板。
- **THEN** 原位置显示“卡片不可用”和“从看板移除”，其他卡片不受影响。

### Requirement: 结构版本迁移
系统 MUST 根据 `schema` 识别布局版本。读到旧版本时先迁移到当前版本再使用，下一次写入时按新结构保存；遇到无法识别的更高版本时 MUST 拒绝写入并提示更新插件。

#### Scenario: 更高版本的布局
- **GIVEN** `board.json` 的 `schema` 是 `hermes-board/layout@2`，而插件只支持 @1。
- **WHEN** 用户尝试移动卡片。
- **THEN** 写入被拒绝，并提示“请更新 hermes-board 插件”，原文件不变。
