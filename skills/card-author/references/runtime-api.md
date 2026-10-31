# 卡片运行时 API（window.HermesCard）

宿主在每张卡片的 `<head>` 最前面注入运行时，卡片脚本中直接使用全局对象 `HermesCard`。所有异步方法都返回 Promise；失败时 reject 一个带 `code` 的 `Error`。

卡片运行在严格 CSP 的沙箱 iframe 中：不能联网、不能访问父页面、不能使用浏览器存储。需要数据时读数据集或序列，需要持久化时用 `state`，需要执行操作时运行脚本。

## 生命周期与环境

```js
HermesCard.ready().then(function (env) {
  // env: { cardId, title, version, size: { w, h, label: '6x4' }, pixel: { width, height },
  //        theme: 'light' | 'dark', locale: 'zh-CN', protocol: 1 }
  render();
});
```

- `HermesCard.ready(): Promise<Env>`：与宿主握手完成后兑现。可以多次调用。
- `HermesCard.env`：握手后的环境对象（握手前为 `null`）。
- `HermesCard.on(type, handler): () => void`：监听宿主事件，返回取消函数。

| 事件 | 参数 | 说明 |
|---|---|---|
| `theme` | `{ theme }` | 浅色/深色切换（令牌变量已自动更新，仅图表等需要重绘时监听） |
| `resize` | `{ size, pixel }` | 用户调整了卡片尺寸 |
| `visibility` | `{ visible }` | 卡片滚出/进入视口、窗口隐藏/显示；不可见时应暂停本地定时器 |
| `changed` | `{ topics }` | 订阅的数据发生变化 |
| `run` | `{ runId, name, status }` | 本卡片某次运行的状态变化 |

## 数据读取

- `HermesCard.data.get(key)` → `{ value, updatedAt }`；从未写入时 `{ value: null, updatedAt: null }`。
- `HermesCard.data.list()` → `{ [key]: { value, updatedAt } }`。
- `HermesCard.series.query(name, { since, until, limit, order })` → `[{ ts, value }]`。`since`/`until` 为 UTC 毫秒；`limit` 默认 1000、最大 5000；`order` 为 `asc`（默认）或 `desc`。

## 卡片状态

- `HermesCard.state.get(key)` → 值；从未写入时返回清单中的 `default`（没有则 `null`）。
- `HermesCard.state.set(key, value)` → `{ updatedAt }`。单值不超过 64 KiB，单卡合计不超过 1 MiB。
- `HermesCard.state.delete(key)` → `{ deleted }`。

状态保存在远程服务端，多台 Desktop 打开同一个看板时共享。

## 订阅变化

```js
var off = HermesCard.subscribe(['data:current', 'series:temp', 'state:city', 'run:*'], function (topic) {
  if (topic === 'data:current') loadCurrent();
});
```

- 主题格式：`data:<key>`、`series:<name>`、`state:<key>`、`run:*`。
- 宿主在看板可见时每 5 秒检查一次变化（隐藏时 30 秒），脚本运行结束时会立即检查。回调参数是发生变化的主题。

## 运行脚本

```js
HermesCard.run('fetch', { city: '上海' }, { wait: true }).then(function (run) {
  // run: { runId, status: 'succeeded' | 'failed' | 'timeout' | ..., result, error, progress, message, ... }
});
```

- `HermesCard.run(name, args?, { wait?, onProgress? })`：只能运行清单中 `callable: true` 的脚本，`args` 先按清单的 `args` Schema 校验。
  - `wait` 为假（默认）时返回 `{ runId, status, deduplicated }`；同一脚本正在运行时直接返回进行中的 `runId`，`deduplicated` 为真。
  - `wait` 为真时等到终态再兑现，返回完整运行记录；`onProgress(run)` 会在进度变化时调用。
  - 调用过快（`minIntervalSec`）时 reject，`code` 为 `rate_limited`，`err.retryAfterMs` 为建议等待时间。
- `HermesCard.scripts.run(name, args)`：等同于不等待的 `HermesCard.run`。
- `HermesCard.runs.get(runId)`、`HermesCard.runs.list(limit)`：查询本卡片的运行记录（每卡保留最近 100 条）。

## AI 任务

- `HermesCard.ai.invoke(name, input)` → `{ parsed, model, provider, usage, runId }`。`name` 必须在清单的 `ai` 中声明；`input` 按 `inputSchema` 校验，`parsed` 一定符合 `outputSchema`。
- 每张卡片每分钟最多 6 次、同时最多 1 次。远程没有可用模型时 reject，`code` 为 `ai_unavailable`。
- AI 只负责给出结构化结论；真正的操作（例如切换节点）由卡片再调用对应的脚本完成，并在界面上展示结论和理由。

## 界面辅助

- `HermesCard.ui.state(el, kind, text?)`：在 `el`（通常是 `.hb-state` 元素）上显示 `loading`、`empty`、`error` 状态，`ready` 时隐藏。
- `HermesCard.ui.updated(el, ts)`：把 `el` 的文字设为“更新于 14:32”（超过一天显示日期）。
- `HermesCard.ui.notify(message, kind?)`：宿主提示，`kind` 为 `info`（默认）、`success`、`warning`、`error`；每卡每 3 秒最多 1 次。
- `HermesCard.ui.remind({ id, at, title, message })`：登记一个定时提醒（`at` 为 UTC 毫秒），即使用户离开看板页面也会按时用系统通知提醒；`HermesCard.ui.cancelRemind(id)` 取消。Desktop 重启后提醒会丢失，卡片应在每次加载时根据自身状态重新登记（番茄钟就是这样做的）。
- `HermesCard.ui.openExternal(url)`：在系统浏览器中打开链接，只允许 `http(s)`，并且必须在用户点击等手势中调用。
- `HermesCard.ui.contextmenu({ x, y })`：打开宿主的卡片菜单。运行时默认会在右键时自动调用，卡片调用 `event.preventDefault()` 可阻止。

## 格式化（中文）

| 方法 | 示例 |
|---|---|
| `HermesCard.fmt.number(1234.5, 1)` | `1,234.5` |
| `HermesCard.fmt.percent(0.423, 1)` | `42.3%` |
| `HermesCard.fmt.bytes(1536000)` | `1.5 MB` |
| `HermesCard.fmt.duration(3723000)` | `1 小时 2 分` |
| `HermesCard.fmt.relative(Date.now() - 90000)` | `1 分钟前` |
| `HermesCard.fmt.time(ts)` / `HermesCard.fmt.date(ts)` | `14:32` / `10月31日` |

## 图表（SVG）

图表绘制到传入的容器元素中，自动使用令牌颜色并跟随主题，容器尺寸变化时需要重新调用。

- `HermesCard.chart.line(el, series, opts)`：`series` 为 `[{ name, points: [{ ts, value }] }]`（也可以直接传点数组）；`opts` 可选 `yFormat`、`xFormat`（函数）、`min`、`max`。第一个系列用强调色，其余用灰阶。
- `HermesCard.chart.sparkline(el, values, opts)`：`values` 为数字数组，迷你折线，无坐标轴。
- `HermesCard.chart.bar(el, items, opts)`：`items` 为 `[{ label, value }]`。
- `HermesCard.chart.ring(el, ratio, opts)`：`ratio` 为 0 到 1；`opts.label` 为中心文字，`opts.status` 为 `positive`、`warning`、`critical` 时使用对应状态色。

## 错误码

| code | 含义 |
|---|---|
| `invalid` | 参数不合法（看 `message`） |
| `not_found` | 卡片、脚本、AI 任务或运行记录不存在 |
| `rate_limited` | 调用过于频繁 |
| `busy` | 同一 AI 任务正在运行，或服务端繁忙 |
| `ai_unavailable` | 远程没有可用模型 |
| `timeout` | 请求超时 |
| `offline` | 与远程 Hermes 的连接中断 |
| `internal` | 其他错误 |
