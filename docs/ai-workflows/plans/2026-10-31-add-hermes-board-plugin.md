# 执行计划：Hermes 看板插件（hermes-board）

| 项目 | 内容 |
|---|---|
| 变更 | `add-hermes-board-plugin` |
| 编制日期 | 2026-10-31 |
| 状态 | **执行计划已编制，实施未开始** |
| 本轮授权 | 用户指示“提交后自动执行 workflow-plan”。本轮只提交基线 `d5102d9` 并编制本计划；不写业务代码，不安装依赖，不改动本机或远程 Hermes 安装 |
| 产品依据 | [提案](../openspec/changes/add-hermes-board-plugin/proposal.md)、7 份能力规格、[技术设计](../openspec/changes/add-hermes-board-plugin/design.md) |
| 对应任务 | [OpenSpec tasks.md](../openspec/changes/add-hermes-board-plugin/tasks.md) |
| 下一工作流 | `workflow-worktree` 准备隔离工作树，然后进入 `workflow-implement`，从 S00 开始 |

## 1. 计划边界与仓库事实

本文件只是已确认 OpenSpec 的执行视图，不是第二套需求。尺寸预设、交互规则、存放位置、桥方法、SQLite 表结构、默认卡片和布局都以规格和 design.md 为准。实施中如果发现规格遗漏或互相矛盾，要暂停受影响的切片，回到 `workflow-spec`，不能自行补行为。

以下仓库与环境事实均为本轮实际核实：

- 仓库：`/Users/liujinglun/ai-app/manus/hermes-blueprint`，分支 `master`，唯一提交是 `d5102d9`（工作流技能、OpenSpec、`openspec` 软链接、`.gitignore`）。没有远程仓库，也没有任何业务代码、`package.json` 或锁文件。
- 本机工具：Node `v26.10.0`、npm `11.19.1`、pnpm `9.15.4`。Hermes venv 为 Python `3.12.13`，自带 fastapi `0.133.1`、httpx `0.28.1`、PyYAML、psutil `7.2.2`。本机 Hermes 为 0.22.2。
- Hermes 宿主接口（已在源码中核实）：
  - `ctx.register_tool(name, toolset, schema, handler, …)`
  - `ctx.register_skill(name, path)`（解析为 `hermes-board:<name>`）
  - `ctx.llm`（`hermes_cli/plugins.py`）
  - `hermes_cli.plugin_events.broadcast_plugin_event(plugin_id, event, payload)`
  - `plugins.plugin_storage.plugin_data_dir(name)`（每次调用都重新解析当前 profile）
  - `cron.jobs` 中的 `create_job`、`update_job`、`pause_job(job_id, reason)`、`resume_job`、`remove_job`、`get_job`、`list_jobs`、`parse_schedule`
  - cron 脚本使用 `tools.environments.local.build_subprocess_env(strip_launch_profile=True)` 构造环境，用 `sys.executable` 运行 `.py`
- Desktop SDK 导出（已在 `apps/desktop/src/sdk/index.ts` 中核实）：`ROUTES_AREA`、`SIDEBAR_NAV_AREA`、`PALETTE_AREA`、`WorkspacePageHeaderControl`、`SandboxedFrame`、`useTheme`、`Popover*`、`ContextMenu*`、`ConfirmDialog`、`EmptyState`、`Button`、`Codicon`、`host`、`useQuery`。插件上下文提供 `ctx.rest`、`ctx.socket`、`ctx.onEvent`、`ctx.setTimeout`、`ctx.setInterval`、`ctx.os.notify`、`ctx.os.openExternal`。`ctx.os.notify` 只在用户离开 Hermes 时弹出，应用内提示要用 `host.notify`。参考插件 hermes-bill 的入口写法是 `export default { id, defaultEnabled, register(ctx) }`。
- 环境限制（实测）：
  - Hermes venv 的 editable 安装缺少顶层模块 `hermes_yaml`，在 hermes-agent 目录外导入宿主模块，必须设置 `PYTHONPATH=~/.hermes/hermes-agent`。
  - 当前执行权限下，运行 `hermes` 命令行会报“install state is not writable”。
  - `cron/jobs.py` 在导入时就固定了 `JOBS_FILE`，所以必须在导入前设置好临时 `HERMES_HOME`。

## 2. 前置门禁与停止条件

| 门禁 | 当前状态 | 实施阶段的处理 | 何时必须停止 |
|---|---|---|---|
| G0 编码授权 | 只有计划授权 | 用户发起 `workflow-implement`（或明确授权编码）后才开始 S01 及之后的切片 | 本轮不得写业务代码 |
| G1 Git 隔离 | 已有基线 `d5102d9`；本计划文件尚未提交 | `workflow-worktree` 先把本计划提交到基线，再建分支 `feat/add-hermes-board-plugin` 和工作树 `.worktrees/add-hermes-board-plugin`（需先把 `.worktrees/` 加入 `.gitignore`） | 基线不干净、工作树检查失败、`.worktrees/` 没有被忽略 |
| G2 依赖安装 | 未安装 | 在工作树内 `pnpm add -D esbuild`（锁定精确版本），生成 `pnpm-lock.yaml`，设置 `packageManager: pnpm@9.15.4`。不安装其他运行时依赖 | 需要全局安装或升级机器级工具时，单独征得同意 |
| G3 写入真实 Hermes | 未授权 | 以下操作都需要用户先明确授权：安装到本机 `~/.hermes/desktop-plugins/hermes-board/` 或 `~/.hermes/plugins/hermes-board/`、修改 `config.yaml` 的 `plugins.enabled`、重启 `hermes serve`、运行 `hermes` 命令行。命令行受当前权限限制，需要授权提权执行，或者由用户自己运行 | 不得为了验证而直接改动用户的真实 profile、cron 任务或已安装插件 |
| G4 远程 Linux 主机 | 未提供连接方式 | 开发期使用本机 macOS 和临时 `HERMES_HOME`；最终验收（S12）前请用户提供 Linux 主机的访问方式或代为执行 | 不能把 macOS 上的结果当作 Linux 验收 |
| G5 发布渠道 | 没有 Git 远程 | “Install from Git”验收需要用户提供可访问的仓库地址（比如新建 GitHub 仓库）。在此之前只用拷贝目录的方式安装验证 | 不能把拷贝安装说成“Install from Git 已验证” |
| G6 技术验证结果 | 未执行 | 按 S01 的结论推进 | V1 不成立：停止全部 Desktop 切片，回到 `workflow-spec`。V2 或 V3 不成立：按规格降级后继续，并在执行记录中注明 |

安全红线：所有自动化测试和验证都必须使用 `mktemp -d` 创建的临时 `HERMES_HOME`，并在写入前断言解析出的路径确实位于这个临时目录下，否则立即中止。任何提交都按 `git-attribution` 追加署名，严禁 `git add .`。

## 3. 实现技术决策与目录

### 3.1 工具链

- **Python**：解释器统一为 `HERMES_PY=~/.hermes/hermes-agent/venv/bin/python`。业务代码只依赖标准库加宿主提供的 FastAPI。宿主模块一律通过 `hermes_board_core/host.py` 适配层延迟导入，导入失败时降级，测试中注入假实现。单元测试不依赖宿主模块。宿主集成测试放在 `tests/host/`，只在设置了 `HERMES_AGENT_ROOT` 时运行，并强制使用临时 `HERMES_HOME`。
- **JS**：源码用原生 ESM `.js`（`package.json` 中 `"type": "module"`），不用 JSX，直接调用 `jsx`/`jsxs`。`scripts/build-desktop.mjs` 分两步调用 esbuild API：
  1. 把 `runtime/src/index.js` 打包成压缩的 IIFE 字符串，并读取 `runtime/card-tokens.css` 的文本；
  2. 打包 `desktop/src/plugin.js`：通过 esbuild 插件提供虚拟模块 `virtual:card-runtime`（导出运行时字符串和 CSS 文本）；输出 `format: esm`、`target: es2022`；把 `@hermes/plugin-sdk`、`react`、`react/jsx-runtime` 设为 external；产物写到 `desktop/plugin.js` 并提交。
- **共享常量**：`shared/constants.json` 是唯一来源，包含列数、预设尺寸、格宽上下限、间距、各种大小限制、`apiVersion`、`protocol`。Python 用 `json` 读取，JS 由 esbuild 以 JSON 形式导入。
- **共享测试用例**：`tests/fixtures/layout-cases.json` 包含吸附、推挤、整理、首次适配、校验几类用例，Python 和 JS 测试都读取它。

### 3.2 模块职责

| 位置 | 模块 | 职责 |
|---|---|---|
| 根目录 | `plugin.yaml`、`__init__.py` | 插件清单（`name: hermes-board`、`provides_tools: [board_manage]`、`requires_hermes` 由 V4 确定）；`register(ctx)` 注册工具和技能，并把 `ctx.llm` 保存到 `ai` 模块 |
| `hermes_board_core/` | `constants.py` | 读取 `shared/constants.json` |
| | `host.py` | 宿主适配：插件数据目录、scripts 目录、子进程环境、事件广播、cron 接口、`parse_schedule`；探测可用性并允许测试注入 |
| | `paths.py` | 路径解析、命名正则、防止路径穿越 |
| | `store.py` | SQLite 建表与迁移、WAL、各类读写、大小限制、分批清理、`changes` 流水 |
| | `layout.py` | DSL 校验与迁移、原子写入、`revision`、409 冲突、首次适配、不可用卡片占位 |
| | `validator.py` | 清单、HTML 安全规则（错误）、设计规则（警告）、Schema 子集；提供命令行 `python -m hermes_board_core.validator <dir…> [--strict]` |
| | `cards.py` | 注册表扫描、两侧原子安装与回滚、`revision`、删除到 trash、SDK 同步 |
| | `runner.py` | 动作执行器：参数校验、单飞、全局并发 4、超时后杀进程组、输出截断、结果解析 |
| | `cron_sync.py` | 绑定表、增量同步、全量对账、可用性降级 |
| | `ai.py` | `ctx.llm` 句柄、输入输出校验、运行记录 |
| | `events.py` | 封装 `layout.updated`、`card.updated`、`card.removed`、`run.finished` 事件 |
| | `init.py` | 在 `.init.lock` 保护下做幂等首次初始化 |
| | `tool.py` | `board_manage` 的 schema 和 9 个操作 |
| `dashboard/` | `manifest.json`、`plugin_api.py` | FastAPI 薄路由层，统一错误格式，加 `no-store` |
| `sdk/` | `hermes_board_sdk.py` | 脚本 SDK（仅标准库） |
| `runtime/` | `card-tokens.css`；`src/{protocol,fmt,chart,ui,index}.js` | 设计令牌和组件类；`window.HermesCard` |
| `desktop/src/` | `plugin.js` | 入口，注册路由、侧边栏、命令面板 |
| | `api.js`、`poller.js` | REST 封装、版本检查；变更轮询（可注入计时器） |
| | `grid-math.js`、`layout-ops.js` | 尺寸计算；吸附、推挤、整理、首次适配、冲突重放（纯函数） |
| | `html-transform.js`、`bridge.js` | 注入与 base64；消息认证、白名单、限流、订阅分发 |
| | `card-host.js`、`board-page.js` | 单卡 iframe 宿主；页面、头部控件、浮动整理按钮 |
| | `gestures.js`、`menus.js`、`dialogs.js` | 覆盖层手柄与指针手势；添加卡片弹层、卡片菜单；“最近运行”和“关于”对话框 |
| `cards/<id>/` | `card.json`、`index.html`、`scripts/*` | 8 张默认卡片 |
| `skills/card-author/` | `SKILL.md`、`references/*.md`、`templates/basic-card/` | 卡片创作技能 |
| `tests/` | `test_*.py`、`host/test_*.py`、`fixtures/` | Python 单元测试与宿主集成测试 |
| `desktop/test/`、`runtime/test/` | `*.test.mjs` | `node --test` |

`desktop/plugin.js` 的 `defaultEnabled` 沿用 hermes-bill 的 `true`：用户本来就要主动安装，启用与停用仍然在 Capabilities 中控制。

## 4. 顺序与切片

主路径：`S00 → S01 → S02 → S03 → S04 → S05 → S06 → S07 → S11 → S09 → S10 → S12`。S08（卡片运行时）在 S02 完成后可以和 S03 到 S07 并行。S09 需要 V1 通过，并且 S06 和 S08 已完成。

每个切片都按同一节奏进行：先写会失败的行为测试，再做最小实现，然后重跑受影响的检查，记录证据，最后勾选 tasks.md 中对应的条目。

### S00：隔离与环境前置（tasks 0.4，门禁 G1、G2）

1. 用 `workflow-worktree` 提交本计划，把 `.worktrees/` 加入 `.gitignore`，建立 `feat/add-hermes-board-plugin` 和对应工作树，之后所有命令都在工作树中执行。
2. 在执行记录中写下第 1 节的工具版本，以及 `HERMES_PY` 和 `PYTHONPATH` 的约定。

**完成标准**：工作树干净，`git log` 显示基线和计划提交。

### S01：技术验证（tasks 1.1–1.4）

验证代码放在工作树内的 `.work/spikes/`（已被 `.gitignore` 忽略），不进入正式产物。

- **V1（需要 G3 授权）**：写一个最小 Desktop 插件，拷贝到本机 `~/.hermes/desktop-plugins/hb-spike/`，在一个页面里渲染 20 个 `SandboxedFrame`（base64 `data:` 文档加注入的 CSP）。确认以下几点并截图存档：`fetch` 被 CSP 拦截；双向 postMessage 正常；`event.source` 加令牌的认证生效；iframe 自导航后会再次触发 `load`；`useTheme().resolvedMode` 可以读取。再用 Activity Monitor 记录 20 个 iframe 的内存增量。验证完删除 `hb-spike`。
- **V2（不需要授权）**：设置 `HERMES_HOME=$(mktemp -d)` 和 `PYTHONPATH=~/.hermes/hermes-agent` 后再导入 `cron.jobs`，断言 `JOBS_FILE` 位于临时目录下。然后依次验证：`create_job(no_agent=True, script="hermes-board/demo/x.py")`、`pause_job`、`resume_job`、`update_job`、`remove_job`；用 `cron.scheduler_script._run_job_script("hermes-board/demo/x.py")` 跑通子目录脚本，并确认 SDK 根据路径反推出临时 `HERMES_HOME`；`parse_schedule("every 30m")` 可用。
- **V3（需要 G3 授权和一个已登录模型的 profile）**：在已启用插件的 `hermes serve` 中，通过 `/health` 确认 `aiAvailable`，并调用一次 `complete_structured`。暂时无法执行时，标记为“待验证”，不阻塞其他切片，只影响 S06 的 AI 真机验证。
- **V4**：从 V1 和 V2 的结果确定 `requires_hermes` 的最低版本，以及 `WorkspacePageHeaderControl`、`ctx.setTimeout`、`ctx.os.notify` 是否可用。

**停止条件**：V1 任意一项不成立时，暂停 S09 和 S10，回到 `workflow-spec`。

### S02：工程骨架与测试入口（tasks 2.1–2.4）

- **文件**：`plugin.yaml`、`__init__.py`（注册工具和技能的空壳）、`dashboard/manifest.json`、`dashboard/plugin_api.py`（只有 `GET /health`）、`shared/constants.json`、`package.json`、`pnpm-lock.yaml`、`scripts/build-desktop.mjs`、`scripts/check-bundle.mjs`、`desktop/src/plugin.js`（只注册路由、侧边栏和一个占位页）、`.gitignore`（`.work/`、`node_modules/`、`__pycache__/`、`.worktrees/`）、`README.md`（安装章节）。
- **先写的测试**：
  - `tests/test_registration.py`：用假 ctx 断言注册了 `board_manage`（工具集 `hermes_board`）和技能 `card-author`。
  - `tests/test_api_health.py`：用 TestClient 请求 `/health`，检查返回字段。
  - `scripts/check-bundle.mjs`：解析产物，断言只导入了允许的 3 个模块，并对产物执行 `node --check`。

**完成标准**：`pnpm build`、`pnpm check`、Python 单元测试都通过。

### S03：路径、SQLite 与布局 DSL（tasks 3.1–3.4）

- **测试**：
  - `test_paths.py`：命名正则；拒绝 `../`、绝对路径和符号链接逃逸。
  - `test_store.py`：建表与 `meta` 版本；数据集、序列、状态读写；超出 256 KiB、4 KiB、64 KiB、1 MiB 的限制；序列按 `maxPoints` 和 `maxAgeDays` 清理；`runs` 保留 100 条；`changes` 流水，以及 `since` 早于保留范围时返回 `reset`。
  - `test_layout.py`：校验规则（越界、不在预设内、不在 sizes 内、重叠、重复、未安装、超过 64 项、未知字段）；原子写入（模拟 rename 前崩溃）；`revision` 和 409；首次适配（读取共享用例）；不可用卡片占位；遇到 `@2` 时拒绝写入。
- **实现**：`paths.py`、`store.py`、`layout.py`、`constants.py`、`host.py`（先实现 `plugin_data_dir` 和 scripts 目录解析）。

**完成标准**：board-layout-dsl 规格的 6 个场景，以及 card-data-scripts 中存储和保留相关的场景都有对应测试并通过。

### S04：卡片包校验与安装（tasks 4.1–4.4）

- **测试**：
  - `test_validator.py`：design.md 第 12 节每条错误和警告规则各至少一个用例，`schedule` 不合法，Schema 超出子集。
  - `test_cards.py`：在两侧临时目录中原子安装；更新时 `revision` 递增；没有 `replace` 时返回 `exists`；路径穿越被拒绝；cron 同步失败时回滚（注入一个会抛异常的假 `CronSync`）；删除到 trash 需要 `confirm`；SDK 按内容哈希同步。
- **实现**：`validator.py`（含命令行）、`cards.py`。cron 通过 `CronSync` 协议注入，S05 提供真实实现。

### S05：脚本 SDK、动作执行器与 cron 同步（tasks 5.1–5.4）

- **测试**：
  - `test_sdk.py`：用子进程在临时目录结构里运行一个示例脚本，验证根据路径推断的结果、data、series、state、progress、result；cron 触发时自动写运行记录且 stdout 为空；异常时记录 `failed`。
  - `test_runner.py`：拒绝非 `callable` 脚本；`args` 校验；`minIntervalSec`；单飞返回 `deduplicated`；全局并发 4（第 5 个排队）；超时后杀掉进程组（脚本再派生一个 `sleep` 子进程来验证）；stdout 截断到 4 KiB；`.sh` 脚本的 `HERMES_BOARD_RESULT` 行；结束时触发 `run.finished` 回调。
  - `test_cron_sync.py`（使用假的 cron 模块）：安装、更新、删除、移出看板、放回看板各自对 cron 的调用序列；全量对账时补建缺失任务、删除孤儿任务；探测不到接口时状态为“定时未接入”。
  - `tests/host/test_cron_host.py`：把 V2 的验证固化为测试，只在设置了 `HERMES_AGENT_ROOT` 时运行。
- **实现**：`sdk/hermes_board_sdk.py`、`runner.py`（环境变量优先用 `host.build_subprocess_env(strip_launch_profile=True)`，回退到最小白名单）、`cron_sync.py`。

### S06：REST API、AI、事件与初始化（tasks 6.1–6.5）

- **测试**：`test_api.py` 用 TestClient 覆盖 design.md 第 9 节每个接口的成功、校验失败和 404，以及 `PUT /board` 的 409、`document?known=` 返回 `unchanged`、`no-store`、统一错误格式。`test_ai.py` 用假 llm 验证输入超限、输出 Schema 校验、运行记录，以及不可用时返回 501。`test_events.py` 断言各写入路径都广播了对应事件。`test_init.py` 用 fixture 卡片目录测试并发初始化（两个进程争用 `.init.lock`）的幂等性。
- **实现**：`plugin_api.py`、`ai.py`、`events.py`、`init.py`。V3 真机验证在 G3 授权后补做。

### S07：Agent 工具与创作技能（tasks 7.1–7.3）

- **测试**：`test_tool.py` 覆盖 9 个操作的成功路径和结构化错误（`exists`、`invalid`、未确认的删除），`save` 之后能放到首个空位并触发 `runOnInstall`，`run` 同步返回 stdout 和 stderr 的末尾。`templates/basic-card` 必须能通过 `validator --strict`。
- **实现**：`tool.py`，以及 `skills/card-author/SKILL.md` 和 4 份参考文档（`design-standard.md`、`manifest.md`、`runtime-api.md`、`script-sdk.md`）。这些文档的内容只从 design.md 第 6、8、10–13 节转写，不新增规则。

### S08：卡片运行时与设计令牌（tasks 8.1–8.3，可与 S03–S07 并行）

- **测试**：`runtime/test/protocol.test.mjs` 测试消息编解码、令牌匹配、`run` 的 wait 在轮询下兑现；`fmt.test.mjs` 测试数字、百分比、字节、时长和中文相对时间；`chart.test.mjs` 检查 line、sparkline、bar、ring 输出的 SVG 结构，以及颜色是否引用令牌变量。
- **实现**：`runtime/card-tokens.css`（浅色和深色令牌、字号阶梯、组件类、`prefers-reduced-motion`），`runtime/src/*.js`。

### S11：默认卡片（tasks 10.1–10.5，需要 S05 和 S08）

- **实现**：按 design.md 第 14 节的表格实现 8 张卡片和默认布局。天气脚本 `cards/weather/scripts/fetch_weather.py` 调用 Open-Meteo 的地理编码和预报接口。网络请求通过可注入的函数完成，测试时用固定数据替代。
- **测试**：`test_default_cards.py` 检查全部卡片通过 `validator --strict`（既无错误也无设计警告）；默认布局覆盖率为 100% 且无重叠；初始化后存在 `hermes-board:weather:fetch` 的绑定；天气脚本在固定数据下写出 `current` 和 `forecast`，城市默认为北京。

### S09：Desktop 基础（tasks 9.1–9.5，需要 V1、S06、S08）

- **测试**：`grid-math.test.mjs` 测格宽限制在 24–72px 之间以及像素换算；`html-transform.test.mjs` 测注入顺序（CSP 在最前）、UTF-8 中文经 base64 往返不变、大小上限；`bridge.test.mjs` 测 `event.source` 不匹配时丢弃、令牌不匹配时丢弃、未知方法、参数超限、每秒 20 次和 AI 每分钟 6 次的限流、卡片 id 由宿主固定；`poller.test.mjs` 测 5 秒和 30 秒切换、事件触发补拉、`reset` 时全量刷新、合并分发给订阅者。
- **实现**：`plugin.js` 中的注册（含 `WorkspacePageHeaderControl` 的特性检测）、`api.js`（`apiVersion` 检查）、`poller.js`、`html-transform.js`、`card-host.js`（10 秒超时、自导航时重建、按 sha 缓存、IntersectionObserver）、`bridge.js`（notify、remind 走 `ctx.setTimeout`，到点时同时调用 `host.notify` 和 `ctx.os.notify`；openExternal；contextmenu）、`board-page.js`（各种错误和空状态、主题、断开标记）。

### S10：交互（tasks 9.6–9.9）

- **测试**：`layout-ops.test.mjs` 读取共享用例，覆盖：两个调整手柄分别固定哪个角、候选尺寸的吸附与取舍规则、贴边时没有候选、推挤连锁、三种候选顺序的整理和评分、已经最紧凑时不写入、撤销生成新版本、409 冲突后在新版本上重放（包含规格中“Agent 新增卡片的同时用户正在拖动”的场景）、键盘移动和切换尺寸。
- **实现**：`gestures.js`（覆盖层热区、圆弧和横条样式、`setPointerCapture`、手势期间屏蔽 iframe 指针事件、Esc 取消）、浮动整理按钮和 200ms 动画、`menus.js`（添加卡片、卡片右键菜单）、`dialogs.js`（最近运行、关于）。

### S12：集成验收与收尾（tasks 7.4、11.1–11.4，门禁 G3、G4、G5）

1. 运行第 5 节的全部命令并通过；`desktop/plugin.js` 与源码一致。
2. 在 G3 授权后，先在本机做开发验收：拷贝方式安装两部分，启用插件并重启 `hermes serve`；用 README 人工清单逐项验证 board-desktop 规格的场景，包括主题切换、Hermes 定时任务页面中能看到 `hermes-board:*` 任务、越权调用被拒绝；把 V3 补测完。
3. 在 G4 和 G5 满足后，在远程 Linux 上执行 `hermes plugins install` 和 `enable`，Desktop 通过 Install from Git 安装，按清单再验收一遍，重点验证 OAuth 远程下 10 秒内的轮询兜底。
4. 通过真实对话让 Hermes 创建一张带定时脚本和按钮操作的新卡片（tasks 11.3），全程不手动改文件。
5. 用 `workflow-close` 做评审和归档。

任何一步没有满足前提时，如实标注“未验证”，不得宣称已完成。

## 5. 验证命令

在工作树根目录执行：

```bash
export HERMES_PY=~/.hermes/hermes-agent/venv/bin/python
pnpm install --frozen-lockfile
pnpm build                               # 生成 desktop/plugin.js
pnpm check                               # check-bundle（导入白名单 + node --check）+ 产物与源码一致（git diff --exit-code desktop/plugin.js）
pnpm test:js                             # node --test "desktop/test/**/*.test.mjs" "runtime/test/**/*.test.mjs"
$HERMES_PY -m unittest discover -s tests -t . -p "test_*.py"
$HERMES_PY -m hermes_board_core.validator cards/* skills/card-author/templates/basic-card --strict
HERMES_AGENT_ROOT=~/.hermes/hermes-agent HERMES_HOME="$(mktemp -d)" \
  PYTHONPATH="$HOME/.hermes/hermes-agent:." $HERMES_PY -m unittest discover -s tests/host -t .
```

`package.json` 中 `test` 脚本会依次执行 JS 测试、Python 单元测试和校验器。宿主集成测试需要 `HERMES_AGENT_ROOT`，所以单独列出，由 S05 和 S12 显式运行。

## 6. 任务覆盖矩阵

| tasks.md | 切片 | tasks.md | 切片 |
|---|---|---|---|
| 0.1、0.3 | 已完成（本轮） | 6.1–6.5 | S06 |
| 0.2 | 本计划 | 7.1–7.3 | S07 |
| 0.4 | S00 | 7.4 | S12 |
| 1.1–1.4 | S01 | 8.1–8.3 | S08 |
| 2.1–2.4 | S02 | 9.1–9.5 | S09 |
| 3.1–3.4 | S03 | 9.6–9.9 | S10 |
| 4.1–4.4 | S04 | 10.1–10.5 | S11 |
| 5.1–5.4 | S05 | 11.1–11.4 | S12 |

规格场景与测试的对应关系：board-layout-dsl 由 S03 覆盖；card-package 由 S04 和 S11 覆盖；card-data-scripts 由 S03、S05、S06 覆盖；card-authoring-agent 由 S07 和 S12 覆盖；card-runtime-bridge 中的纯逻辑由 S08 和 S09 覆盖，真实沙箱行为由 V1 和 S12 覆盖；board-desktop 中的纯逻辑由 S10 覆盖，交互表现由 S12 的人工清单覆盖；default-cards 由 S11 和 S12 覆盖。

## 7. 当前交付与后续接力

本轮完成了基线提交 `d5102d9` 和本计划。本计划文件尚未提交，会在 S00 中由 `workflow-worktree` 一并提交。下一步：用户确认后执行 `workflow-worktree`，然后用 `workflow-implement` 从 S00 和 S01 开始。V1 和 V3 需要 G3 授权（往本机 Hermes 安装验证插件），最终验收需要 G4（Linux 主机访问方式）和 G5（Git 发布地址），届时会逐项向用户确认。
