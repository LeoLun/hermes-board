# 能力规格：数据脚本、SQLite 存储与原生 cron

状态：已确认（2026-10-31 16:10 用户指示进入计划阶段）。定时刷新方式对应 [proposal.md](../../proposal.md) 确认记录第 9 项，技术细节见 [design.md](../../design.md) 第 7、8 节。

## ADDED Requirements

### Requirement: 统一的 SQLite 存储
系统 MUST 把所有卡片数据存放在 `$HERMES_HOME/plugin-data/hermes-board/board.sqlite3`，开启 WAL，使用 design.md 第 7 节定义的标准表：`datasets`（数据集快照）、`series_points`（时间序列）、`card_state`（卡片状态）、`runs`（运行记录）、`changes`（变更流水）、`cron_bindings`（cron 绑定）。每一行都以卡片 id 隔离，时间戳统一为 UTC 毫秒。结构版本记录在 `meta` 表中，升级时按版本顺序迁移。

#### Scenario: 首次访问
- **GIVEN** 远程还没有数据库。
- **WHEN** 第一次调用 API 或工具。
- **THEN** 系统创建数据库和所有表，并把结构版本记为 1。

### Requirement: 写入限制与保留策略
系统 MUST 限制数据集单值不超过 256 KiB、序列单点不超过 4 KiB。序列默认保留 30 天且最多 20000 点，清单可以按序列覆盖；`runs` 每张卡片保留最近 100 条；`changes` 保留 24 小时。清理 MUST 分批进行，不能阻塞正常写入。

#### Scenario: 序列超过上限
- **GIVEN** 某序列声明了 `maxPoints: 2000`。
- **WHEN** 脚本写入第 2201 个点并触发了清理。
- **THEN** 这个序列只保留最新的 2000 个点。

### Requirement: 脚本 SDK
系统 MUST 提供只依赖标准库的 Python SDK `hermes_board_sdk.py`，并在初始化和插件版本变化时把它同步到 `$HERMES_HOME/scripts/hermes-board/_sdk/`。SDK MUST 能根据脚本所在路径推断卡片 id 和 `HERMES_HOME`，不依赖环境变量；MUST 提供 `data.set/get`、`series.append`、`state.get`、`progress`、`result`、`args`、`trigger`。cron 触发时 SDK MUST 自己写一条运行记录，并且不向 stdout 输出任何内容。

#### Scenario: cron 环境下运行
- **GIVEN** cron 以清洗过的环境变量运行 `scripts/hermes-board/weather/fetch_weather.py`。
- **WHEN** 脚本调用 `Card().data.set('current', {...})`。
- **THEN** 数据写进 `weather` 卡片的 `current` 数据集，`runs` 中多一条 `trigger=cron` 的成功记录，cron 没有输出可投递的内容。

### Requirement: 点击触发脚本
系统 MUST 通过 `POST /cards/{id}/runs` 运行清单中标记为 `callable` 的脚本，并且 MUST：按 `args` Schema 校验参数，参数通过临时 JSON 文件传入，不经过 shell 拼接；检查 `minIntervalSec`；同一卡片的同一脚本同时只运行一个（重复请求返回正在进行的运行 id，并标记 `deduplicated`）；全局最多同时运行 4 个；超时（默认 60 秒，最大 600 秒）后杀掉整个进程组；只保存 stdout 和 stderr 的末尾 4 KiB；结束时写入终态、追加变更，并广播 `run.finished`。

#### Scenario: 运行超时
- **GIVEN** 脚本的 `timeoutSec` 是 30。
- **WHEN** 脚本运行超过 30 秒。
- **THEN** 进程组被终止，运行状态为 `timeout`，卡片收到终态。

#### Scenario: 参数不合法
- **WHEN** 卡片传入的 `args` 不符合清单 Schema。
- **THEN** 返回 `invalid`，不启动子进程。

### Requirement: 原生 cron 同步
系统 MUST 为每个带 `schedule` 的脚本创建一条 Hermes 原生 cron 任务：`no_agent=True`，名称为 `hermes-board:<card>:<script>`，`script` 为 `hermes-board/<card>/<file>`，`deliver=local`。系统 MUST 在卡片安装或更新、删除、从看板移除（暂停）、重新放回看板（恢复）时同步这些任务。首次初始化和插件版本变化时 MUST 全量对账：补建缺失的任务，删除名称前缀为 `hermes-board:` 但没有对应卡片的任务。cron 接口不可用时，MUST 把卡片的定时状态标为“定时未接入”，手动运行不受影响。

#### Scenario: 在 Hermes 定时任务页查看
- **GIVEN** 已安装天气卡片。
- **WHEN** 用户打开 Hermes 的定时任务页面。
- **THEN** 能看到 `hermes-board:weather:fetch`，每 30 分钟运行一次，可以在原生界面暂停或查看运行历史。

#### Scenario: 移出看板时暂停
- **WHEN** 用户把天气卡片移出看板。
- **THEN** 对应的 cron 任务被暂停；重新添加后恢复。

### Requirement: AI 任务执行
系统 MUST 用插件 LLM 能力 `ctx.llm.complete_structured` 执行清单中声明的 AI 任务，使用用户当前的 provider 和模型，校验输入（不超过 32 KiB）和输出 Schema，并写一条 `kind='ai'` 的运行记录。不可用时 MUST 返回 `501 ai_unavailable`，并在 `/health` 中报告。

#### Scenario: 结构化选择
- **GIVEN** 卡片声明了 AI 任务 `choose`，`outputSchema` 要求 `{choice, reason}`。
- **WHEN** 卡片用一组候选数据调用该任务。
- **THEN** 返回解析好的 `{choice, reason}` 以及 model 和 usage 信息。

### Requirement: 远程 REST API
系统 MUST 在 `/api/plugins/hermes-board/` 下提供 design.md 第 9 节列出的接口。所有响应都带 `Cache-Control: no-store`，错误统一返回 `{detail:{code,message}}`；`/health` MUST 报告插件版本、`apiVersion`、结构版本、`cronAvailable`、`aiAvailable`。API MUST NOT 提供上传或修改卡片源码的入口。

#### Scenario: 版本不兼容
- **GIVEN** 远程的 `apiVersion` 高于 Desktop 端支持的版本。
- **WHEN** Desktop 打开看板。
- **THEN** 页面顶部提示“请更新 Desktop 插件”，不发出任何写操作。
