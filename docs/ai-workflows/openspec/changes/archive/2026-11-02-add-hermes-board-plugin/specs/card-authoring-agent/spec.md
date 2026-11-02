# 能力规格：通过对话创建卡片（Agent 工具与技能）

状态：已确认（2026-10-31 16:10 用户指示进入计划阶段）。工具和技能的设计见 [design.md](../../design.md) 第 13 节。

## ADDED Requirements

### Requirement: board_manage 工具
系统 MUST 在远程 Agent 端注册工具 `board_manage`（工具集 `hermes_board`），通过 `action` 支持：`list`、`get`、`validate`、`save`、`remove`、`run`、`data`、`place`、`restore_default`。工具出错时 MUST 返回结构化 JSON（`{ok:false, code, message, details}`），不抛异常；成功时返回摘要、警告和相关运行 id。

#### Scenario: 列出卡片
- **WHEN** Agent 调用 `board_manage {action:'list'}`。
- **THEN** 返回每张卡片的 id、标题、版本、是否在看板上、脚本及 cron 状态、最近运行，以及布局概要。

### Requirement: 保存卡片包
`save` MUST 依次执行以下步骤：校验，出现错误就终止；原子安装；同步 SDK；对账 cron；在后台运行 `runOnInstall` 脚本；新卡片按默认尺寸放到首个空位（或者放到调用方指定的合法位置）；递增卡片 `revision` 和布局版本；广播 `card.updated` 和 `layout.updated`。更新已有卡片时 MUST 显式传入 `replace: true`。

#### Scenario: 对话创建新卡片
- **GIVEN** 用户在对话中说“帮我做一张显示远程主机磁盘使用率的卡片”。
- **WHEN** Agent 按技能流程生成卡片包并调用 `save`。
- **THEN** 卡片安装成功并出现在看板的空位上，cron 开始按计划写数据。已打开的 Desktop 看板在 10 秒内显示这张新卡片。

#### Scenario: 未声明替换就覆盖
- **WHEN** Agent 对一个已存在的卡片 id 调用 `save`，但没有传 `replace: true`。
- **THEN** 返回 `exists` 错误，原卡片保持不变。

### Requirement: 自测能力
系统 MUST 让 Agent 能用 `run` 同步运行卡片脚本，拿到结果和 stdout、stderr 的末尾内容；能用 `data` 读取数据集、序列、状态和运行记录。这样 Agent 可以在告诉用户“完成”之前确认数据已经正确生成。

#### Scenario: 脚本报错
- **WHEN** Agent 用 `run` 运行一个有语法错误的脚本。
- **THEN** 返回失败状态、退出码和 stderr 末尾内容，Agent 能据此修复后重新 `save`。

### Requirement: 卡片创作技能
系统 MUST 随插件提供技能 `hermes-board:card-author`，内容包括：创建流程（澄清需求和尺寸 → 用模板起草 → validate → save → run/data 自测 → 告知用户查看）；完整的设计标准、清单规范、运行时 API 和脚本 SDK 参考；至少一个包含清单、HTML 和脚本的基础模板；安全约束（卡片不联网、取数放在脚本里、凭据走 `terminal.env_passthrough`、特权操作需要用户在远程自行授权）；以及无人值守 AI 决策的做法（由 Agent 创建调用 `board_manage` 的普通 cron agent 任务）。

#### Scenario: 用户要求带按钮的卡片
- **WHEN** 用户要求“点一下就重启某个服务”的卡片。
- **THEN** Agent 按技能把操作写成 `callable` 脚本，卡片通过 `HermesCard.run` 触发。如果需要 sudo，Agent 先说明需要用户在远程配置权限，不会把密码写进卡片文件。

### Requirement: 删除需要确认
`remove` 默认只从看板移除并暂停 cron。只有在 `deletePackage: true` 且 `confirm: true` 时，MUST 才执行彻底删除。Agent 在对话中执行彻底删除之前，SHOULD 先得到用户的明确同意。

#### Scenario: 用户只是不想看到某张卡片
- **WHEN** 用户说“先把待办卡片从看板拿掉”。
- **THEN** Agent 调用 `remove`（不删除包），卡片之后还可以通过“添加卡片”恢复。
