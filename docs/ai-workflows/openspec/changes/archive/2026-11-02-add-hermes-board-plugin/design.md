# 技术设计：Hermes 看板插件（hermes-board）

状态：已确认（2026-10-31 16:10）。产品层面的决定以 [proposal.md](./proposal.md) 的确认记录为准。本文是给实现阶段用的技术基线，标为“实现验证项”的内容需要在开发早期用最小原型确认。

## 1. 总体架构

```
Hermes Desktop（本机 macOS）                          hermes serve（远程 Linux）
┌────────────────────────────────────┐   ctx.rest   ┌──────────────────────────────────────────┐
│ desktop/plugin.js                  │ ───────────▶ │ dashboard/plugin_api.py  /api/plugins/    │
│  ├ 侧边栏「看板」+ 路由 /hermes-board │ ◀─ 事件/轮询 ─ │   hermes-board/*                          │
│  ├ 网格引擎（移动/尺寸/整理）        │              │ hermes_board_core/                        │
│  ├ 卡片宿主 ×N                     │              │  ├ store（board.sqlite3）                 │
│  │   SandboxedFrame(data: URL)     │              │  ├ layout（board.json DSL）               │
│  │   ├ 注入：CSP + 令牌 CSS + 运行时 │              │  ├ cards（卡片包注册/校验/安装）           │
│  │   └ 卡片 HTML ── postMessage ─┐  │              │  ├ runner（动作脚本执行）                 │
│  └ 桥（白名单、限流、固定卡片 id）◀─┘  │              │  ├ cron_sync（原生 cron 同步）            │
└────────────────────────────────────┘              │  └ ai（ctx.llm 结构化调用）               │
                                                    │ __init__.py：board_manage 工具 + 技能      │
                                                    │ Hermes cron（no_agent）→ scripts/hermes-board/<卡片>/*.py │
                                                    └──────────────────────────────────────────┘
```

信任模型如下。卡片包只能由远程 Agent 工具或内置默认包安装。卡片脚本以远程 Hermes 用户的权限运行任意代码，因此卡片包的可信程度等同于远程主机。Desktop 把卡片 HTML 当作**不可信的访客内容**：iframe 的 origin 不透明，CSP 禁止联网；桥只开放该卡片自己命名空间下的白名单方法，卡片 id 由宿主固定，卡片自己无法指定。这样即使远程被攻破或卡片写得有问题，也无法借卡片拿到本机 App 权限、凭据或其他卡片的数据。

## 2. 仓库结构

```
plugin.yaml                     # name: hermes-board，provides_tools: [board_manage]
__init__.py                     # register(ctx)：工具、技能、保存 ctx.llm 句柄
hermes_board_core/
  paths.py  store.py  layout.py  cards.py  validator.py
  runner.py  cron_sync.py  ai.py  init.py  events.py
dashboard/
  manifest.json                 # { "name": "hermes-board", "api": "plugin_api.py" }
  plugin_api.py                 # FastAPI router（薄层，调用 hermes_board_core）
sdk/hermes_board_sdk.py         # 脚本 SDK（仅标准库），运行时同步到远程 scripts 目录
runtime/
  card-runtime.js               # window.HermesCard（注入 iframe）
  card-tokens.css               # 设计令牌 + 组件类
desktop/
  src/                          # 模块化源码：plugin、board-page、grid、gestures、arrange、
                                #   card-host、bridge、html-transform、api、poller
  plugin.js                     # esbuild 打包产物（提交到仓库；runtime 以字符串内联）
cards/                          # 内置默认卡片包（8 个）
  weather/ clock/ calendar/ world-clock/ countdown/ pomodoro/ note/ todo/
    card.json  index.html  [scripts/*.py]
skills/card-author/
  SKILL.md  references/{design-standard,manifest,runtime-api,script-sdk}.md  templates/
tests/                          # Python unittest；tests/fixtures/*.json 供 Python 与 JS 共用
desktop/test/                   # node --test
package.json                    # devDependencies: esbuild；scripts: build / test:js / check
README.md
```

Python 内部包取名 `hermes_board_core`，是为了避免和其他插件加入 `sys.path` 后的模块重名。参考插件 hermes-bill 的 `plugin_api.py` 会把插件根目录插入 `sys.path`，本插件沿用这个做法。

## 3. 远程存放位置

所有路径都基于当前 profile 的 `HERMES_HOME`，通过 Hermes 的 `plugins.plugin_storage.plugin_data_dir("hermes-board")` 解析，每次调用都重新解析，不缓存，这样切换 profile 时会跟着走。

```
$HERMES_HOME/plugin-data/hermes-board/
  board.json                    # 布局 DSL（权威）
  board.sqlite3 (+ -wal/-shm)   # 数据
  cards/<card-id>/
    card.json                   # 清单
    index.html                  # 唯一入口（单文件，≤ 256 KiB）
  trash/<card-id>-<UTC时间戳>/   # 删除卡片包时移入
  .init.lock  .install.lock     # 进程间文件锁
$HERMES_HOME/scripts/hermes-board/
  _sdk/hermes_board_sdk.py      # 插件按内容哈希同步
  <card-id>/<script>.py|.sh     # 卡片脚本（cron 要求必须在 scripts/ 下）
```

一个卡片包实际分布在两个根目录下：HTML 和清单在 `plugin-data`，脚本在 `scripts`（这是 cron 的限制）。工具和 API 屏蔽了这一点，Agent 和用户不需要直接写这些路径。

命名规则：卡片 id 匹配 `^[a-z][a-z0-9-]{1,47}$`；脚本名（清单中的键）匹配 `^[a-z][a-z0-9_]{0,31}$`；脚本文件名匹配 `^[a-z0-9_-]{1,48}\.(py|sh)$`；数据键、序列名、状态键匹配 `^[A-Za-z0-9_.-]{1,64}$`。

## 4. 布局 DSL（board.json）

```json
{
  "schema": "hermes-board/layout@1",
  "boardId": "default",
  "title": "看板",
  "revision": 12,
  "updatedAt": "2026-10-31T08:00:00Z",
  "updatedBy": "desktop",
  "grid": { "columns": 24 },
  "items": [
    { "id": "weather", "card": "weather", "x": 0, "y": 0, "w": 8, "h": 8 }
  ]
}
```

- 坐标单位是格。`x ∈ [0, 23]`，`y ≥ 0`，`x + w ≤ 24`。`(w, h)` 必须同时属于全局预设和该卡片清单的 `sizes`。卡片之间不能重叠，最多 64 项。
- 全局预设尺寸 `PRESETS`：`4x4, 4x6, 6x4, 6x6, 8x4, 8x6, 8x8, 12x6, 12x8`（宽×高）。
- `id` 是实例 id。v1 每个卡片包最多放一个实例，并要求 `id == card`，多实例留到以后。`boardId` 为多看板预留，v1 固定为 `default`。
- 写入方式：先写临时文件，再 `fsync` 后 `rename` 原子替换；每次写入 `revision + 1`。只有 `revision`、`updatedAt`、`updatedBy` 由服务端维护，客户端提交的这几个字段会被忽略。
- 并发控制：`PUT /board` 必须带 `baseRevision`。不一致时返回 `409` 和当前文档。Desktop 收到 409 后，在最新文档上重放这一次用户操作（移动或调整某张卡片到目标矩形，再做推挤），并重试一次；仍然失败就以服务端为准刷新，并提示“布局已在其他地方更新”。
- 布局里引用了不存在或校验失败的卡片时，仍然保留它的占位，页面显示“卡片不可用”，并提供移除入口，不会静默丢弃。
- 结构版本升级时，读取方先做迁移，再按新结构写回。

## 5. 网格、交互与算法（Desktop）

### 5.1 尺寸计算

页面内边距 `P = 16px`，格间距 `G = 12px`，格宽 `c = (W − 2P − 23G) / 24`，并限制在 `[24px, 72px]` 之间。行高等于 `c`，即格子是正方形。卡片像素宽度为 `w·c + (w−1)·G`，高度同理。`c` 达到上限时看板定宽居中；达到下限时出现横向滚动。纵向不限，页面可滚动。窗口尺寸变化在 100ms 防抖后重新计算，并给每张卡片发送 `resize` 事件。

### 5.2 悬停手柄（宿主覆盖层）

iframe 会吞掉鼠标事件，所以手柄放在 iframe **上方的覆盖层**里。覆盖层只有手柄区域响应鼠标，其余区域穿透给卡片。

- **移动横条**：位于卡片顶部中间，热区宽度为卡片宽的 40%（限制在 48–120px），高 16px。悬停时显示一条 36×5px 的胶囊横条，颜色为 `var(--ui-text-quaternary)`，距顶部 6px。光标为 `grab`，拖动中为 `grabbing`。
- **调整手柄**：左下角和右下角各一个 24×24px 热区。悬停时沿卡片圆角（18px）画出 3px 粗的四分之一圆弧，光标分别为 `nesw-resize` 和 `nwse-resize`。卡片只声明了一种尺寸时不显示调整手柄。
- 手柄只在悬停卡片或键盘聚焦时显示，拖动其他卡片时一律隐藏。

### 5.3 拖动与调整

- 指针按下后使用 `setPointerCapture`，手势期间所有 iframe 设为 `pointer-events: none`。按 Esc 取消并还原。
- **移动**：卡片半透明跟随指针，目标位置四舍五入到格子并限制在边界内。原位置下方实时显示吸附后的占位预览，松手后提交。
- **调整**：右下手柄固定左上角，左下手柄固定右上角（`x` 随之变化）。根据指针算出期望的 `(w*, h*)`（以格为单位的浮点数），在“全局预设 ∩ 卡片 sizes ∩ 在固定点下能放进 24 列”的候选尺寸中，选与期望值欧氏距离最小的一个；距离相同时取面积更小的；没有候选时保持原尺寸。预览框上显示尺寸标签，比如 `6×4`。iframe 在松手后才真正改变尺寸。
- **推挤**：活动卡片放到目标矩形后，与它重叠的卡片按 `(y, x)` 顺序下移到刚好不再冲突的位置，被挤下去的卡片再连锁处理。拖动和调整期间都实时预览推挤结果。不做自动上移压缩，留下的空隙交给“自动整理”处理。
- 每次手势只产生一次 `PUT /board`。
- 键盘（SHOULD）：聚焦移动横条后，方向键按 1 格移动，`Shift+方向键` 在允许的尺寸之间切换，`Enter` 或失焦时提交。

### 5.4 自动整理

页面右下角固定一个圆形浮动按钮，提示文字为“自动整理”。它只改位置、不改尺寸。算法是确定性的启发式：

1. 准备三种候选顺序：阅读顺序 `(y, x)`；面积从大到小，相同则按阅读顺序；高度从大到小、再宽度从大到小，相同则按阅读顺序。
2. 对每种顺序做首次适配放置：依次为每张卡片找“`y` 最小、其次 `x` 最小”且不与已放置卡片重叠的位置。
3. 按 `(总高度, 卡片位移总和 Σ|Δx|+|Δy|)` 比较三种结果，取字典序最小的一个。
4. 如果结果和当前布局相同，提示“已经是最紧凑的排布”，不写入。否则用 200ms 动画过渡，写入一次新版本，并弹出带“撤销”的提示；撤销会把原布局作为又一个新版本写回。

同一份布局测试用例 `tests/fixtures/layout-cases.json` 同时给 JS 测试（推挤、吸附、整理）和 Python 测试（新卡片首次适配放置、DSL 校验）使用，保证两边行为一致。

### 5.5 页面结构与其他界面

- 注册内容：`ROUTES_AREA` 路由 `/hermes-board`；`SIDEBAR_NAV_AREA` `{ label: '看板', codicon: 'dashboard' }`；`PALETTE_AREA` 中的“打开看板”“看板：自动整理”“看板：重新加载”。
- 页面头部用 `WorkspacePageHeaderControl` 放置“添加卡片”按钮和同步状态。这个控件要通过命名空间导入做特性检测，旧版本 Desktop 上回退为页面内联显示。“添加卡片”弹层列出已安装但不在看板上的卡片（标题、描述、默认尺寸），点击后按默认尺寸放到首个空位。
- 卡片菜单：右键卡片任意位置（运行时会把 iframe 内的 `contextmenu` 转发给宿主）或右键移动横条，弹出宿主菜单，包含“刷新”“立即运行 ‹脚本›”“最近运行”“关于此卡片”“从看板移除”。
- 状态展示：卡片 10 秒内没有发出 `ready` 时，显示“卡片加载失败 · 重试”；后端返回 404 时显示安装或启用指引（远程 `hermes plugins enable hermes-board` 并重启 `hermes serve`）；401 时提示到 Settings → Gateways 重新登录；断开连接时保留最后一次画面，并显示“已断开”标记。
- 主题：看板外框只使用 `var(--ui-*)` 主题变量。卡片通过 `useTheme().resolvedMode` 得到 `light` 或 `dark` 并传进 iframe。
- 性能：卡片进入视口时才挂载 iframe（IntersectionObserver，SHOULD）。卡片文档按（连接、profile、卡片、sha256）缓存在内存里，只有内容哈希变化时才重建 iframe。

## 6. 卡片宿主与桥协议

### 6.1 文档转换

Desktop 调用 `GET /cards/{id}/document?known=<sha>` 拿到 `{html, sha256, revision}`，或者在哈希未变时拿到 `{unchanged: true}`。然后在 `<head>` 的**最前面**依次注入：

1. `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'">`
2. `<meta name="color-scheme" content="light dark">`
3. `<style id="hb-tokens">`：设计令牌和组件类，见第 10 节。
4. `<script id="hb-runtime">`：运行时，带上本次挂载的随机令牌、卡片 id、协议版本、初始主题、尺寸和语言。

转换后的 HTML 编码为 UTF-8 后做 base64，生成 `data:text/html;base64,…`，交给 `SandboxedFrame`（sandbox 只用默认的 `allow-scripts`）。卡片原始 HTML 限制在 256 KiB 以内，转换后约 0.4 MiB，远低于 Chromium 对 URL 的 2 MiB 限制。iframe 的 `title` 设为卡片标题。

**实现验证项 V1**：确认在 Hermes Desktop 的 `SandboxedFrame` 中，`data:` 文档、注入的 meta CSP 和 postMessage 双向通信都能正常工作，并测量 8 到 20 个 iframe 时的内存占用。

### 6.2 消息格式

所有消息形如 `{ ns: 'hermes-board', v: 1, type, token, ... }`。宿主只接受同时满足 `event.source === iframe.contentWindow` 且 `token` 匹配的消息，其余丢弃并在调试日志中记录。

- 握手：运行时发送 `ready`，宿主回复 `init`（携带 env）。
- 请求与响应：运行时发送 `{type:'request', id, method, params}`，宿主回复 `{type:'response', id, ok, result | error:{code, message}}`。
- 宿主主动推送的事件：`theme`、`resize`、`visibility`、`changed`（订阅项变化）、`run`（运行状态变化）。
- 导航防护：iframe 首次 `load` 之后如果再次触发 `load`，说明卡片文档发生了自导航，宿主会重建 iframe 并记录日志。

### 6.3 桥方法白名单（v1）

| 方法 | 说明 | 后端 |
|---|---|---|
| `env.get` | `{cardId, title, version, size:{w,h,label}, pixel:{width,height}, theme, locale:'zh-CN', protocol:1}` | 本地 |
| `data.get(key)` / `data.list()` | 数据集快照 `{value, updatedAt}` | GET data |
| `series.query(name, {since, until, limit≤5000, order})` | 时间序列点 `[{ts, value}]` | GET series |
| `state.get/set/delete(key, value)` | 卡片自身状态，单值 ≤ 64 KiB，单卡合计 ≤ 1 MiB | state |
| `scripts.run(name, args)` | 运行清单中 `callable` 的脚本，返回 `{runId, status, deduplicated}` | POST runs |
| `runs.get(runId)` / `runs.list(limit)` | 运行状态、进度和结果 | GET runs |
| `ai.invoke(name, input)` | 调用清单中声明的 AI 任务，返回结构化结果 | POST ai |
| `subscribe(topics)` | 订阅 `data:<key>`、`series:<name>`、`state:<key>`、`run:*` | 宿主轮询 |
| `ui.notify({message, kind})` | 宿主提示（每卡每 3 秒最多 1 次） | 本地 |
| `ui.remind({id, at, title, message})` / `ui.cancelRemind(id)` | 插件级定时提醒，见下文 | 本地 |
| `ui.openExternal(url)` | 只允许 http(s)，且必须由用户手势触发 | `ctx.os.openExternal` |
| `ui.contextmenu({x, y})` | 打开宿主卡片菜单 | 本地 |

宿主会对每次请求做以下处理：用宿主持有的卡片 id 拼接 REST 路径；校验参数类型和大小；限流（每卡每秒最多 20 个请求，AI 调用每卡每分钟最多 6 次，同一时间最多 1 个）。运行时会把 `scripts.run` 包装成 `HermesCard.run(name, args, {wait})`：`wait` 为真时，等到终态再兑现 Promise。

`ui.remind` 的定时器挂在插件级的 `ctx.setTimeout` 上，即使离开看板页面也会按时用 `host.notify` 或 `ctx.os.notify` 提醒；App 重启后丢失，等卡片下次加载时根据自身状态重新登记。番茄钟就是用这个方式解决“离开页面后错过提醒”的问题。

### 6.4 变更感知

Desktop 在看板页面挂载且窗口可见时，每 5 秒轮询一次 `GET /changes?since=<seq>`，窗口不可见时改为 30 秒；收到 `plugin.hermes-board.*` 事件或本卡片运行结束时，立即补拉一次。根据返回的变更记录，Desktop 给订阅了对应主题的卡片推送 `changed`。如果出现 `layout` 或 `card` 类变更，则重新拉取 `/board` 或卡片文档。如果 `since` 早于服务端保留的最小序号，返回 `reset: true`，所有订阅都会刷新一次。

## 7. 服务端存储（board.sqlite3）

数据库启用 WAL，`busy_timeout = 5000ms`，记录在 `meta` 表中的结构版本为 1。所有时间戳都是 UTC 毫秒。

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE datasets (card_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL, PRIMARY KEY (card_id, key));
CREATE TABLE series_points (id INTEGER PRIMARY KEY, card_id TEXT NOT NULL, series TEXT NOT NULL,
  ts INTEGER NOT NULL, value_json TEXT NOT NULL);
CREATE INDEX idx_series ON series_points (card_id, series, ts);
CREATE TABLE card_state (card_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL, PRIMARY KEY (card_id, key));
CREATE TABLE runs (run_id TEXT PRIMARY KEY, card_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('script','ai')), name TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('cron','action','install','tool','manual')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','timeout','cancelled')),
  progress REAL, message TEXT, created_at INTEGER NOT NULL, started_at INTEGER, finished_at INTEGER,
  exit_code INTEGER, result_json TEXT, error TEXT, stdout_tail TEXT, stderr_tail TEXT);
CREATE INDEX idx_runs_card ON runs (card_id, created_at DESC);
CREATE TABLE changes (seq INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('data','series','state','run','card','layout')),
  name TEXT, at INTEGER NOT NULL);
CREATE TABLE cron_bindings (card_id TEXT NOT NULL, script TEXT NOT NULL, job_id TEXT NOT NULL,
  schedule TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (card_id, script));
```

保留与限制：

- 数据集单值 ≤ 256 KiB，序列单点 ≤ 4 KiB。
- 序列默认保留 30 天且最多 20000 点，清单可按序列覆盖。清理在写入时分批进行，每写入 200 次或距上次清理超过 10 分钟时执行一次。
- `runs` 每卡保留最近 100 条，`changes` 保留 24 小时。
- 每次写入都追加一条 `changes` 记录。

## 8. 脚本：SDK、执行与 cron

### 8.1 SDK 用法（hermes_board_sdk.py，仅标准库）

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card

card = Card()                        # 根据脚本路径推断卡片 id 和 HERMES_HOME
city = card.state.get("city", "北京")
card.data.set("current", {...})      # 数据集快照
card.series.append("temp", 21.5)     # 时间序列，ts 默认为当前时间
card.progress(0.4, "正在处理第 2/5 项")
card.result({"ok": True})            # 动作结果；cron 触发时不输出
```

- 推断方式：脚本位于 `$HERMES_HOME/scripts/hermes-board/<card>/x.py`，所以 `parents[3]` 就是 `HERMES_HOME`，父目录名就是卡片 id。这样不依赖环境变量，cron 清洗过的环境里也能工作。SDK 会检查对应的 `plugin-data/.../cards/<card>/card.json` 是否存在。
- 运行上下文：动作执行器会设置 `HERMES_BOARD_RUN_ID`、`HERMES_BOARD_TRIGGER`、`HERMES_BOARD_ARGS_FILE` 三个环境变量。没有这些变量时视为 cron 触发，此时 SDK 会自己在 `runs` 中写一条记录，并在退出时（`atexit` 或异常钩子）写入终态。因此 cron 触发和动作触发的运行记录格式一致。
- 输出约定：cron 触发时 SDK 不向 stdout 输出任何内容，cron 就会静默；异常退出码非零，由 cron 按原生方式记录和告警。不使用 SDK 的 `.sh` 脚本，可以在最后一行输出 `HERMES_BOARD_RESULT {json}` 来返回动作结果。

### 8.2 动作执行器（runner）

`POST /cards/{id}/runs {script, args}` 的处理步骤：

1. 校验脚本已声明且 `callable`，`args` 符合清单里的 `args` JSON Schema 子集。
2. 检查最小间隔 `minIntervalSec`。
3. 单飞：同一张卡片的同一个脚本正在运行时，直接返回正在进行的 `runId`，并标记 `deduplicated: true`。
4. 写入一条 `queued` 记录，交给后台线程池执行（全局最多同时运行 4 个）。
5. 子进程命令为 `[sys.executable, path]` 或 `["bash", path]`，工作目录是脚本所在目录，参数写入临时 JSON 文件传递，不经过 shell 拼接。环境变量与 Hermes cron 脚本保持一致：优先复用 Hermes 的脚本环境清洗逻辑；不能复用时，只保留最小白名单（`PATH`、`HOME`、`LANG`、`TZ`）加上 `terminal.env_passthrough` 声明的变量。
6. 超时取 `timeoutSec`（默认 60 秒，最大 600 秒），超时后杀掉整个进程组。stdout 和 stderr 各最多读取 64 KiB，只保存末尾 4 KiB。
7. 结束时写入终态，追加 `run` 变更，并调用 `broadcast_plugin_event('hermes-board', 'run.finished', …)`。

### 8.3 原生 cron 同步（cron_sync）

- 清单中带 `schedule` 的脚本，对应一条 cron 任务：`create_job(prompt=None, schedule=…, name="hermes-board:<card>:<script>", script="hermes-board/<card>/<file>", no_agent=True, deliver="local")`。对应关系记录在 `cron_bindings` 表中。
- 触发同步的时机：卡片安装或更新（schedule、文件变化）、卡片删除（删除任务）、从看板移除（暂停任务）、重新放回看板（恢复任务）。另外首次初始化和插件版本变化时做一次全量对账：补建缺失的任务；名称前缀为 `hermes-board:` 但没有对应卡片的孤儿任务直接删除。
- 所有 cron 调用都通过一个适配层访问 `cron.jobs` 模块（`create_job`、`update_job`、`remove_job`，以及暂停和恢复）。**实现验证项 V2**：确认这些函数在 `hermes serve` 进程内可以安全调用、按 profile 隔离，并找出暂停和恢复的正式接口。如果适配层探测不到可用接口，卡片的 cron 状态显示“定时未接入”，手动运行不受影响。
- 远程必须有正在运行的 cron 调度器（`hermes serve` 或 gateway）。卡片会显示“更新于 …”，便于发现数据过期。

### 8.4 AI 任务

清单中的 `ai.<name>` 声明 `system`（提示词）、`inputSchema`、`outputSchema`、`maxTokens`（≤ 2000）。`POST /cards/{id}/ai/{name} {input}` 会先校验输入（≤ 32 KiB），再调用 `ctx.llm.complete_structured(messages=[system, user:JSON], json_schema=outputSchema, purpose="hermes-board.<card>.<name>")`，返回 `{parsed, model, provider, usage}`，并写一条 `kind='ai'` 的运行记录。这里使用用户当前的 provider 和模型，不申请覆盖信任门槛。`register(ctx)` 会把 `ctx.llm` 保存到 `hermes_board_core.ai` 的模块级变量里，供同一进程中的 `plugin_api` 使用。**实现验证项 V3**：确认插件 API 能拿到这个句柄；拿不到时 `/health` 报告 `aiAvailable:false`，AI 接口返回 `501 ai_unavailable`。

无人值守的 AI 决策，比如定时检测并自动切换，不在卡片内实现。做法是由 Agent 创建一条普通的 Hermes cron agent 任务，让它调用 `board_manage` 的 `run` 和 `data` 操作。技能文档会说明这个模式。

## 9. REST API（/api/plugins/hermes-board）

| 方法与路径 | 说明 |
|---|---|
| `GET /health` | `{ok, pluginVersion, apiVersion:1, schemaVersion, cronAvailable, aiAvailable}` |
| `GET /board` | `{layout, cards:[{id,title,description,version,revision,sizes,defaultSize,status,errors?,scripts:[{name,schedule,callable,cron:{jobId,paused}|null,lastRun}]}]}` |
| `PUT /board` | `{baseRevision, items}`，成功返回 `{layout}`，版本不一致返回 `409 {current}` |
| `POST /board/items` | `{baseRevision, card, size?, x?, y?}`，没有给位置时放到首个空位，并恢复该卡片的 cron |
| `DELETE /board/items/{id}?baseRevision=` | 从看板移除，并暂停该卡片的 cron |
| `GET /cards/{id}/document?known=` | `{html, sha256, revision}` 或 `{unchanged:true}` |
| `GET /cards/{id}/data[/{key}]` | 数据集 |
| `GET /cards/{id}/series/{name}?since&until&limit&order` | 序列 |
| `GET/PUT/DELETE /cards/{id}/state/{key}` | 卡片状态（PUT 请求体为 `{value}`） |
| `POST /cards/{id}/runs` / `GET /cards/{id}/runs?limit` / `GET /runs/{runId}` | 运行 |
| `POST /cards/{id}/ai/{name}` | AI 任务 |
| `GET /changes?since=` | `{seq, changes:[{card,kind,name}], reset?}` |

所有响应都带 `Cache-Control: no-store`。错误统一返回 `{detail:{code,message}}`，错误码包括 `not_found`、`invalid`、`conflict`、`rate_limited`、`busy`、`ai_unavailable`、`cron_unavailable`。Desktop 端不提供上传或修改卡片源码的接口。`/health` 中的 `apiVersion` 用来检测本机和远程的版本是否一致：不兼容时页面顶部提示“请更新远程插件”或“请更新 Desktop 插件”。

## 10. 卡片设计标准（基于 Apple DESIGN.md）

完整标准写在技能文档 `skills/card-author/references/design-standard.md` 里，并由运行时 CSS 实现。要点如下。

- **令牌**：浅色模式下，`--hb-surface #ffffff`、`--hb-surface-2 #fafafc`（Pearl）、`--hb-ink #1d1d1f`、`--hb-ink-2 #333333`、`--hb-ink-muted #7a7a7a`、`--hb-hairline rgba(0,0,0,.08)`、`--hb-divider #f0f0f0`、`--hb-accent #0066cc`、`--hb-focus #0071e3`。深色模式下，`--hb-surface #272729`、`--hb-surface-2 #2a2a2c`、`--hb-ink #ffffff`、`--hb-ink-2 #cccccc`、`--hb-ink-muted #7a7a7a`、`--hb-hairline rgba(255,255,255,.08)`、`--hb-accent #2997ff`。另有状态色扩展，**只能用于表达状态**：`--hb-positive #34c759/#30d158`、`--hb-warning #ff9500/#ff9f0a`、`--hb-critical #ff3b30/#ff453a`。原文只有一个强调色，这是为监控类卡片补充的 Apple 系统色。图表的主系列用强调色，其他系列用灰阶。
- **字体**：`-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", system-ui, sans-serif`，数字一律用 `tabular-nums`。字重只用 300、400、600，不用 500。字号阶梯：`hb-metric-lg` 40/600/1.1；`hb-metric` 34/600/1.1，字距 -0.374px；`hb-metric-sm` 21/600/1.19；`hb-title` 14/600/1.29，字距 -0.224px；`hb-body` 14/400/1.43；`hb-body-lg` 17/400/1.47，字距 -0.374px；`hb-fine` 12/400/1.33；`hb-micro` 10/400/1.3。17px 以上的字号使用负字距。
- **间距与圆角**：以 8px 为基准。卡片内边距：宽度不超过 6 格时 16px，8 格及以上时 24px。卡片圆角为 18px，由宿主外框裁切；内部浅色块 11px，工具按钮 8px，主要按钮、胶囊标签和输入框用全圆角。
- **层次**：卡片内部不用阴影、不用渐变、不加装饰性边框，层次只靠表面色和发丝线区分。
- **组件类**：`hb-card`（根元素 `<main>`）、`hb-header`、`hb-title`、`hb-btn`（强调色全圆角）、`hb-btn--secondary`（描边全圆角）、`hb-btn--utility`（8px 圆角）、`hb-input`、`hb-chip`、`hb-list`、`hb-row`、`hb-well`、`hb-state`（加载、空、错误三态）、`hb-updated`（“更新于 14:32”）。按下时 `scale(.95)`，焦点环为 2px `--hb-focus`。动效时长 200ms，遵守 `prefers-reduced-motion`。
- **尺寸适配**：运行时会在 `<html>` 上设置 `data-size="6x4"`、`data-w`、`data-h`、`data-theme`。卡片在它声明的每一种尺寸下都不能出现整体滚动条，列表只允许在高度不少于 6 格时内部滚动。
- **运行时辅助**：`HermesCard.fmt`（数字、百分比、字节、时长、相对时间，均为中文格式）；`HermesCard.chart.line/sparkline/bar/ring`（SVG，自动使用令牌颜色并跟随主题）；`HermesCard.ui.state(el, kind, text)`。

## 11. 卡片清单（card.json）

```json
{
  "schema": "hermes-board/card@1",
  "id": "weather",
  "title": "天气",
  "description": "当前天气与未来三天预报",
  "version": "1.0.0",
  "entry": "index.html",
  "sizes": ["4x4", "8x4", "8x8"],
  "defaultSize": "8x8",
  "scripts": {
    "fetch": { "file": "fetch_weather.py", "schedule": "every 30m", "runOnInstall": true,
               "callable": true, "timeoutSec": 60, "minIntervalSec": 30,
               "args": { "type": "object", "properties": {}, "additionalProperties": false } }
  },
  "datasets": { "current": { "description": "当前天气" }, "forecast": { "description": "三日预报" } },
  "series": { "temp": { "retention": { "maxAgeDays": 7, "maxPoints": 2000 } } },
  "state": { "city": { "default": "北京" } },
  "ai": {}
}
```

`args` 只支持 JSON Schema 的一个子集：`type`、`properties`、`required`、`enum`、`minimum`、`maximum`、`maxLength`、`items`、`additionalProperties`。`revision` 由服务端在每次安装或更新时自增，不写在清单里。

## 12. 校验（validator）

**错误（阻止安装）**：

- 清单结构不合法。
- 入口文件缺失，或 HTML 超过 256 KiB。
- 引用了外部资源（`src`/`href`/`url()`/`@import` 指向 `http(s):` 或 `//`）。
- 使用了 `<base>`、`<iframe>`、`<object>`、`<embed>`、带 `action` 的 `<form>`。
- 出现 `fetch(`、`XMLHttpRequest`、`WebSocket`、`EventSource`、`sendBeacon`、`localStorage`、`sessionStorage`、`indexedDB`、`document.cookie`、`window.open`、`parent.`/`top.` 等字样。
- `sizes` 不是预设尺寸的子集，或 `defaultSize` 不在 `sizes` 里。
- 脚本文件缺失或命名不合法，`schedule` 无法被 cron 的 `parse_schedule` 解析，以及 `args`/`ai` 的 Schema 不合法。

**警告（允许安装但会返回给 Agent）**：

- 在令牌之外写死颜色（hex、rgb、hsl）。
- 自定义 `font-family`、使用 `box-shadow` 或渐变、字重 500 或 700。
- 缺少 `<main class="hb-card">`、缺少 `lang="zh-CN"`、没有处理加载、空、错误状态。

CSP 才是真正的安全边界，lint 只是为了让 Agent 在安装前尽早得到反馈。

## 13. Agent 工具与技能

`board_manage` 是单个工具，通过 `action` 区分操作。工具出错时返回 JSON 错误，不抛异常。

- `list`：列出卡片、是否在看板上、版本、脚本和 cron 状态、最近运行，以及布局概要。
- `get {card}`：返回清单、HTML、脚本源码，用于修改已有卡片。
- `validate {package}`：只校验，不写入。
- `save {package, place?: "auto"|{x,y,size}, replace?}`：先校验；然后在临时目录准备好 plugin-data 和 scripts 两侧的文件，加安装锁后用 rename 原子落盘；同步 SDK；对账 cron；后台运行 `runOnInstall` 脚本；新卡片自动放到首个空位；最后广播 `card.updated` 和 `layout.updated`。返回警告列表和运行 id。更新已有卡片时必须传 `replace: true`。
- `remove {card, deletePackage?, confirm:true}`：默认只从看板移除并暂停 cron。`deletePackage` 为真时，同时删除 cron、把文件移入 trash，并清除该卡片的数据。
- `run {card, script, args?, wait?}`：运行脚本，返回结果以及 stdout 和 stderr 的末尾内容，用于 Agent 自测或 cron agent 任务。
- `data {card, kind, name?, limit?}`：读取数据集、序列、状态或运行记录，用于验证。
- `place {card, x, y, size}`：调整位置或尺寸，带推挤。
- `restore_default {card}`：从插件内置包重新安装某张默认卡片。

技能 `hermes-board:card-author` 规定了生成卡片的流程：先澄清需求和展示尺寸；从 `templates/` 起草清单、HTML 和脚本；`validate`；`save`；用 `run` 和 `data` 自测；最后告诉用户去“看板”页面查看。技能还写明：卡片内不能联网，取数一律放在脚本里；凭据通过 `terminal.env_passthrough` 提供，不写进卡片文件；需要特权的操作，比如重启系统服务，要由用户在远程自行配置权限，卡片只调用已授权的命令。

## 14. 初始化与默认卡片

第一次调用 API 或工具时，在 `.init.lock` 保护下检查：如果 `board.json` 不存在，就从插件的 `cards/` 安装 8 张默认卡片，写入默认布局，对账 cron，运行 `runOnInstall` 脚本。之后插件升级不会覆盖已有卡片，用户可以用 `restore_default` 手动恢复。

| 卡片 | id | 允许尺寸 | 默认尺寸 / 位置 | 数据 |
|---|---|---|---|---|
| 天气 | `weather` | 4x4, 8x4, 8x8 | 8x8 @ (0,0) | 脚本每 30 分钟从 Open-Meteo 获取数据（地理编码和预报接口，无需密钥）；城市存在状态 `city` 中，默认“北京”，可在卡片内修改并立即刷新 |
| 时钟 | `clock` | 4x4, 6x4, 8x4 | 8x4 @ (8,0) | 纯前端，使用 Desktop 本机时间 |
| 世界时钟 | `world-clock` | 4x4, 8x4 | 4x4 @ (8,4) | 纯前端 Intl，城市列表存在状态中，默认纽约、伦敦、东京 |
| 倒数日 | `countdown` | 4x4, 6x4 | 4x4 @ (12,4) | 目标日期和名称存在状态中，默认“元旦” |
| 日历 | `calendar` | 4x4, 6x6, 8x8 | 8x8 @ (16,0) | 纯前端月历，高亮今天 |
| 番茄钟 | `pomodoro` | 4x4, 6x6, 8x8 | 8x8 @ (0,8) | 状态中保存阶段和起止时间戳（25/5 分钟）；到点用 `ui.remind` 提醒 |
| 便签 | `note` | 6x6, 8x4, 8x8 | 8x8 @ (8,8) | 文本存在状态中，停止输入 800ms 后自动保存 |
| 待办 | `todo` | 6x6, 8x8 | 8x8 @ (16,8) | 列表存在状态中，支持新增、勾选、删除 |

上述 8 张卡片恰好无缝铺满 24×16 网格，在默认窗口（约 1280×800）下基本是一整屏。

## 15. 能力覆盖检查（不在本次交付范围）

以下示例只用来检查平台能力够不够用，不是本次的交付内容：

- **机器监控类**：用 cron 每分钟写序列，卡片可见时由卡片自己定时调用可执行脚本做实时刷新（受 `minIntervalSec` 限制），配合 `chart.sparkline` 和 `ring` 展示。Hermes venv 自带 psutil 7.2.2，温度可以通过 `psutil.sensors_temperatures()` 读取，Linux 上可用。
- **节点测速与切换类**：可执行脚本带参数、长时间运行时上报进度、单飞去重、`ai.invoke` 结构化选择，再执行切换脚本；自动模式由 Agent 创建 cron agent 任务调用 `board_manage run`。
- **账单折线类**：脚本以只读方式读取同机其他数据源，比如 `plugin-data/hermes-bill/bills.sqlite3`，汇总后写入数据集，卡片用 `chart.line` 展示。

## 16. 测试与验证

- **Python**：`unittest` 加临时 `HERMES_HOME`，覆盖路径与命名、DSL 校验与迁移、首次适配放置、SQLite 读写与保留策略、清单与 HTML 校验、动作执行器（超时、单飞、参数校验、结果解析）、用假 cron 模块测试对账逻辑、API（FastAPI `TestClient`）、工具的各个操作、初始化幂等。
- **JS**：`node --test` 覆盖尺寸计算、吸附、推挤、自动整理、HTML 注入与 base64、桥消息校验与限流、轮询合并逻辑。共用 `tests/fixtures/layout-cases.json`。打包后执行 `node --check desktop/plugin.js`。
- **人工**：在远程 Linux 上安装并启用插件，在 Desktop 上通过 Install from Git 安装；按 `README.md` 中的清单逐项验证交互、对话创建卡片、cron 页面中的任务、OAuth 远程下的轮询兜底，以及越权调用被拒绝。

## 17. 风险与实现验证项

- **V1** `data:` 文档、CSP 和 postMessage 在 `SandboxedFrame` 中的行为，以及多个 iframe 的内存开销：最先用最小原型验证；如果不成立，必须回到 workflow-spec 重新选择承载方案。
- **V2** 从插件进程调用 cron 接口的稳定性和 profile 隔离：用适配层隔离，探测到接口不可用时降级为“定时未接入”。
- **V3** `ctx.llm` 能否在插件 API 中使用：不可用时 AI 能力降级，并在 `/health` 中如实报告。
- Hermes 内置 Kanban 的中文名同样是“看板”：已接受，用不同图标区分。
- 本机和远程两半的版本不一致：通过 `apiVersion` 检测并提示。
- 卡片脚本以 Hermes 用户权限执行任意代码：这是设计上的取舍，由安装入口（只有 Agent 工具和内置包）和技能约束来管理。
