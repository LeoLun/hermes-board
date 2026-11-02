# 能力规格：卡片包标准与设计规范

状态：已确认（2026-10-31 16:10 用户指示进入计划阶段）。存放位置、清单、设计令牌和校验规则见 [design.md](../../design.md) 第 3、10、11、12 节。

## ADDED Requirements

### Requirement: 规范的存放位置
系统 MUST 把卡片的清单和 HTML 存放在 `$HERMES_HOME/plugin-data/hermes-board/cards/<card-id>/`（`card.json`、`index.html`），把脚本存放在 `$HERMES_HOME/scripts/hermes-board/<card-id>/`，把脚本 SDK 存放在 `$HERMES_HOME/scripts/hermes-board/_sdk/`。所有路径都基于当前 profile 的 `HERMES_HOME` 解析。卡片 id、脚本名和文件名 MUST 符合 design.md 第 3 节的命名规则，任何越出这些目录的路径 MUST 被拒绝。

#### Scenario: 路径穿越
- **WHEN** 待安装的卡片包里有一个名为 `../../evil.py` 的脚本文件。
- **THEN** 安装被拒绝，返回命名不合法的错误，磁盘上不产生任何文件。

### Requirement: 卡片清单
系统 MUST 要求每张卡片都有 `card.json`（`schema: hermes-board/card@1`），包含 `id`、`title`、`description`、`version`、`entry`、`sizes`、`defaultSize`，以及可选的 `scripts`、`datasets`、`series`、`state`、`ai`。`sizes` 必须是全局预设的非空子集，`defaultSize` 必须属于 `sizes`。每次安装或更新时，服务端 MUST 递增卡片的 `revision`。

#### Scenario: 默认尺寸不在允许范围内
- **WHEN** 清单中 `sizes` 为 `["4x4"]`，`defaultSize` 却是 `"8x8"`。
- **THEN** 校验失败，返回字段级错误。

### Requirement: 单文件 HTML 规范
系统 MUST 要求卡片入口是一个自包含的 HTML 文件，不超过 256 KiB。样式、脚本和图片都必须内联（图片使用 `data:`），不能引用任何外部资源，不能使用网络、浏览器存储、弹窗或访问父窗口的 API。卡片只能通过 `window.HermesCard` 获取数据和执行操作。

#### Scenario: 引用 CDN 脚本
- **WHEN** 卡片 HTML 中有 `<script src="https://cdn.example.com/chart.js">`。
- **THEN** 校验报错并阻止安装，错误信息说明应改用运行时提供的 `HermesCard.chart`。

### Requirement: 统一视觉标准
系统 MUST 提供基于 Apple DESIGN.md 的设计令牌和组件类（design.md 第 10 节），由 Desktop 注入每张卡片：字体栈、字号阶梯、只用 300/400/600 字重、8px 间距基准、18px 卡片圆角、全圆角按钮、单一强调色（浅色 `#0066cc`，深色 `#2997ff`）、发丝线分隔、不用阴影和渐变，以及只用于表达状态的系统色扩展。卡片 SHOULD 只用这些令牌和组件类表达样式。卡片在它声明的每一种尺寸下都 MUST 不出现整体滚动条，并且 MUST 适配浅色和深色模式。

#### Scenario: 写死颜色
- **WHEN** 卡片 CSS 中出现 `color: #333`。
- **THEN** 可以安装，但校验结果中有警告，建议改用 `var(--hb-ink-2)`。

#### Scenario: 深色模式
- **GIVEN** 卡片只使用了令牌颜色。
- **WHEN** Hermes 切换到深色主题。
- **THEN** 卡片表面变为 `#272729`，正文变为白色，强调色变为 `#2997ff`，不需要卡片自己处理。

### Requirement: 安装前校验
系统 MUST 在安装或更新卡片包之前运行校验器，区分“错误”（阻止安装）和“警告”（允许安装，并在结果中返回）。规则见 design.md 第 12 节。cron `schedule` MUST 能被 Hermes cron 的解析器接受，`args`、`ai` 中的 Schema MUST 属于支持的子集。

#### Scenario: 只校验不安装
- **WHEN** Agent 调用 `board_manage validate`。
- **THEN** 返回错误和警告列表，不写入任何文件，不修改 cron。

### Requirement: 原子安装与更新
系统 MUST 在安装锁的保护下，先在临时目录准备好 plugin-data 和 scripts 两侧的文件，再整体替换。任一步骤失败时 MUST 回滚到安装前的状态，包括已经修改的 cron。更新已有卡片 MUST 显式声明替换。

#### Scenario: cron 同步失败
- **GIVEN** 文件已准备好，但创建 cron 任务时报错。
- **WHEN** 安装流程处理这个错误。
- **THEN** 卡片包和 cron 都恢复到安装前的状态，返回错误原因。

### Requirement: 删除卡片包
系统 MUST 只在调用方明确确认时才删除卡片包：删除对应 cron 任务，把两侧文件移入 `plugin-data/hermes-board/trash/<card-id>-<时间戳>/`，清除该卡片在 SQLite 中的数据，并把它从布局中移除。

#### Scenario: 没有确认就删除
- **WHEN** 调用 `remove` 时 `deletePackage: true` 但没有 `confirm: true`。
- **THEN** 操作被拒绝，什么都不改。
