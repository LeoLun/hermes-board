# 能力规格：卡片沙箱、运行时与数据桥

状态：已确认（2026-10-31 16:10 用户指示进入计划阶段）。协议细节见 [design.md](../../design.md) 第 6 节。

## ADDED Requirements

### Requirement: 每张卡片独立沙箱加载
系统 MUST 给每张卡片使用一个独立的 SDK `SandboxedFrame`。文档内容从远程 `GET /cards/{id}/document` 获取，在 `<head>` 最前面注入 CSP、`color-scheme`、设计令牌 CSS 和运行时脚本，再编码成 `data:text/html;base64,…` 加载。sandbox 只开启 `allow-scripts`，origin 不透明。卡片之间、卡片与 App 之间 MUST 不共享任何 DOM、存储或凭据。

#### Scenario: 卡片尝试读取 App
- **WHEN** 卡片脚本访问 `parent.document` 或 `window.top.location`。
- **THEN** 浏览器以跨源错误拒绝访问，App 和其他卡片不受影响。

### Requirement: 禁止卡片联网
系统 MUST 通过注入的 CSP（`default-src 'none'; connect-src 'none'`，只允许内联脚本和样式，图片、字体、媒体只允许 `data:`/`blob:`）阻止卡片发起任何网络请求或加载外部资源。远程数据只能通过运行时桥获取。

#### Scenario: 卡片调用 fetch
- **WHEN** 卡片运行时执行 `fetch('https://example.com')`。
- **THEN** 请求被 CSP 拦截，卡片收到网络错误，不会有任何流量离开本机。

### Requirement: 桥消息认证
系统 MUST 只处理同时满足以下两个条件的 postMessage：`event.source` 等于该卡片 iframe 的 `contentWindow`，且消息里的 `token` 等于本次挂载生成的随机令牌。其他消息一律丢弃。卡片文档自导航（再次触发 `load`）后，系统 MUST 重建该 iframe 并生成新令牌。

#### Scenario: 伪造来源
- **WHEN** 另一张卡片向父窗口发送带有本卡片 id 的请求。
- **THEN** 因 `event.source` 不匹配而被丢弃，不会产生任何 REST 调用。

### Requirement: 方法白名单与卡片作用域
系统 MUST 只开放 design.md 第 6.3 节列出的方法：`env`、`data`、`series`、`state`、`scripts.run`、`runs`、`ai.invoke`、`subscribe`，以及 `ui.notify`/`remind`/`openExternal`/`contextmenu`。宿主 MUST 用自己持有的卡片 id 拼接请求路径，卡片无法访问其他卡片的命名空间。系统 MUST 校验参数的类型和大小，并按卡片限流：每秒最多 20 个请求；AI 调用每分钟最多 6 次，同一时间最多 1 个。

#### Scenario: 调用未开放的方法
- **WHEN** 卡片请求方法 `fs.readFile`。
- **THEN** 收到 `{ok:false, error:{code:'unknown_method'}}`。

#### Scenario: 请求频率过高
- **WHEN** 卡片在一秒内发出 50 个 `data.get`。
- **THEN** 超出部分返回 `rate_limited`，看板和其他卡片的响应不受影响。

### Requirement: 数据读取
运行时 MUST 提供：`data.get(key)` 和 `data.list()`，返回 `{value, updatedAt}`；`series.query(name, {since, until, limit≤5000, order})`，返回 `[{ts, value}]`；`state.get/set/delete`，单值不超过 64 KiB，单卡合计不超过 1 MiB。卡片 HTML 只能写自己的 `state`，MUST NOT 写数据集或序列。

#### Scenario: 读取尚未生成的数据
- **GIVEN** 脚本还没有运行过。
- **WHEN** 卡片调用 `data.get('current')`。
- **THEN** 得到 `null`，卡片显示自己的空状态。

### Requirement: 变更订阅
系统 MUST 允许卡片订阅 `data:<key>`、`series:<name>`、`state:<key>`、`run:*`。Desktop 通过轮询 `/changes`（页面可见时每 5 秒，窗口不可见时每 30 秒），加上插件事件和本卡片运行结束时的即时补拉，在变化发生后 MUST 把 `changed` 事件推送给订阅了它的卡片。在不支持 WebSocket 的远程上，同样 MUST 在 10 秒内送达。

#### Scenario: cron 刷新数据
- **GIVEN** 天气卡片订阅了 `data:current`。
- **WHEN** cron 运行天气脚本并写入新数据。
- **THEN** 下一次轮询后卡片收到 `changed`，重新读取并显示新数据。

### Requirement: 在卡片中触发脚本
运行时 MUST 提供 `HermesCard.run(name, args, {wait})`，只能运行清单中标记为 `callable` 的脚本。它返回运行 id；`wait` 为真时等到终态再返回结果。运行过程中 MUST 能拿到进度（`progress`、`message`）。

#### Scenario: 点击按钮执行操作
- **GIVEN** 卡片清单声明了可执行脚本 `refresh`。
- **WHEN** 用户点击卡片里的“刷新”按钮，卡片调用 `HermesCard.run('refresh', {}, {wait:true})`。
- **THEN** 远程执行该脚本，Promise 以脚本返回的结果兑现，卡片据此更新界面。

### Requirement: AI 结构化调用
运行时 MUST 提供 `HermesCard.ai.invoke(name, input)`，调用清单中声明的 AI 任务，返回符合 `outputSchema` 的结构化结果。远程 AI 不可用时 MUST 返回 `ai_unavailable`，不能让卡片一直挂起。

#### Scenario: AI 不可用
- **GIVEN** `/health` 报告 `aiAvailable:false`。
- **WHEN** 卡片调用 `ai.invoke`。
- **THEN** 立即得到 `ai_unavailable` 错误，卡片显示降级提示。

### Requirement: 环境与尺寸事件
运行时 MUST 在 `<html>` 上维护 `data-size`、`data-w`、`data-h`、`data-theme`，并通过 `HermesCard.on('resize'|'theme'|'visibility'|'changed', fn)` 通知卡片。`HermesCard.env` MUST 提供卡片 id、标题、版本、格尺寸、像素尺寸、主题、语言（`zh-CN`）和协议版本。

#### Scenario: 调整尺寸后
- **WHEN** 用户把卡片从 4×4 调整到 8×4。
- **THEN** `<html data-size>` 变为 `8x4`，卡片收到 `resize` 事件并切换到宽版布局。

### Requirement: 界面辅助能力
运行时 MUST 提供 `HermesCard.fmt`（数字、百分比、字节、时长、中文相对时间）、`HermesCard.chart.line/sparkline/bar/ring`（SVG 图表，使用令牌颜色，跟随主题）和 `HermesCard.ui.state(el, 'loading'|'empty'|'error', text)`。宿主 MUST 提供 `ui.notify`（每卡每 3 秒最多 1 次）、`ui.remind`/`cancelRemind`（插件级定时提醒，离开看板页面后仍然生效）、`ui.openExternal`（只允许 http(s) 且必须由用户手势触发），以及把卡片内的右键转发为宿主菜单。

#### Scenario: 番茄钟到点时不在看板页
- **GIVEN** 番茄钟登记了 25 分钟后的提醒，用户随后切换到对话页面。
- **WHEN** 到达提醒时间。
- **THEN** Desktop 弹出提醒通知，回到看板时番茄钟显示已进入休息阶段。

### Requirement: 加载超时与隔离
系统 MUST 在卡片 10 秒内没有完成握手时显示“卡片加载失败 · 重试”。单张卡片的异常、超时或越权请求 MUST NOT 影响其他卡片和看板交互。

#### Scenario: 卡片死循环
- **GIVEN** 某张卡片的脚本陷入死循环，一直没有发出 `ready`。
- **WHEN** 等待超过 10 秒。
- **THEN** 这张卡片显示加载失败，其他卡片和拖拽交互保持正常。
