# card.json 清单

## 示例

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

`revision` 由服务端在每次安装或更新时自增，不要写在清单里。清单中出现未列出的字段会被拒绝。

## 顶层字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema` | 是 | 固定为 `hermes-board/card@1` |
| `id` | 是 | 卡片 id，正则 `^[a-z][a-z0-9-]{1,47}$` |
| `title` | 是 | 卡片标题（菜单、iframe 标题中显示） |
| `description` | 是 | 一句话说明，出现在“添加卡片”列表里 |
| `version` | 是 | 语义化版本 `x.y.z` |
| `entry` | 是 | 固定为 `index.html` |
| `sizes` | 是 | 允许的尺寸，必须是预设尺寸的子集 |
| `defaultSize` | 是 | 默认尺寸，必须在 `sizes` 中 |
| `scripts` | 否 | 数据脚本声明，键是脚本名 |
| `datasets` | 否 | 数据集声明（仅说明用途） |
| `series` | 否 | 时间序列声明，可覆盖保留策略 |
| `state` | 否 | 卡片状态声明，可设默认值 |
| `ai` | 否 | AI 任务声明 |

## 尺寸

看板为 24 列网格，尺寸写作“宽x高”（单位为格）。预设尺寸只有：`4x4`、`4x6`、`6x4`、`6x6`、`8x4`、`8x6`、`8x8`、`12x6`、`12x8`。一张卡片通常声明 1 到 4 种尺寸，并保证在每一种尺寸下都能完整显示（见 design-standard.md 的“尺寸适配”）。

## 命名规则

| 对象 | 正则 |
|---|---|
| 卡片 id | `^[a-z][a-z0-9-]{1,47}$` |
| 脚本名、AI 任务名 | `^[a-z][a-z0-9_]{0,31}$` |
| 脚本文件名 | `^[a-z0-9_-]{1,48}\.(py|sh)$`（直接放在 `scripts/` 下，不能有子目录） |
| 数据集、序列、状态的键 | `^[A-Za-z0-9_.-]{1,64}$` |

## scripts

| 字段 | 说明 |
|---|---|
| `file` | 脚本文件名（`.py` 用 Hermes 的 Python 运行，`.sh` 用 bash 运行） |
| `schedule` | 可选。定时刷新，由 Hermes 原生 cron 以 no-agent 方式运行 |
| `runOnInstall` | 可选。安装或更新后立即在后台运行一次 |
| `callable` | 可选。为 true 时卡片可以通过 `HermesCard.run` 调用 |
| `timeoutSec` | 可选。卡片/工具触发时的超时，默认 60，最大 600；超时后整个进程组被终止 |
| `minIntervalSec` | 可选。卡片或工具触发的最小间隔，过快调用返回 `rate_limited` |
| `args` | 可选。参数的 JSON Schema（子集），卡片传入的参数先按它校验 |
| `description` | 可选。说明 |

`schedule` 格式（必须能被 Hermes cron 的 `parse_schedule` 解析，最小间隔 1 分钟）：

- 间隔：`every 1m`、`every 30m`、`every 2h`、`every 1d`
- 每天定点：`every 1d at 09:00`
- 5 段 cron 表达式：`*/5 * * * *`、`0 9 * * 1-5`

定时任务在 Hermes 的 cron 页面中显示为 `hermes-board:<卡片>:<脚本>`。卡片不在看板上时，定时任务自动暂停；放回看板后恢复。

## datasets、series、state

- `datasets.<key>`：`{ "description" }`。数据集是“最新快照”，单值不超过 256 KiB。
- `series.<name>`：`{ "description", "retention": { "maxAgeDays", "maxPoints" } }`。默认保留 30 天、最多 20000 点；单点不超过 4 KiB。
- `state.<key>`：`{ "description", "default" }`。状态由卡片自己读写（如城市、待办列表），单值不超过 64 KiB，单卡合计不超过 1 MiB。从未写入时读取返回 `default`。

## ai

```json
"ai": {
  "pick": {
    "description": "从测速结果里选择最优节点",
    "system": "你是网络工程师。根据延迟和丢包选出最优节点，只输出 JSON。",
    "inputSchema": { "type": "object", "required": ["nodes"], "properties": { "nodes": { "type": "array" } } },
    "outputSchema": { "type": "object", "required": ["node"], "additionalProperties": false,
                      "properties": { "node": { "type": "string" }, "reason": { "type": "string" } } },
    "maxTokens": 800
  }
}
```

- `system`、`inputSchema`、`outputSchema` 必填；`maxTokens` 默认 1000，最大 2000。
- 输入（JSON 序列化后）不超过 32 KiB；模型输出必须符合 `outputSchema`，否则返回 `invalid`。
- 远程 Hermes 没有可用的插件模型接口时返回 `ai_unavailable`，卡片应提示用户并保留手动操作。

## Schema 子集

`args`、`inputSchema`、`outputSchema` 只支持这些关键字：`type`（object、array、string、number、integer、boolean、null）、`properties`、`required`、`enum`、`minimum`、`maximum`、`maxLength`、`items`、`additionalProperties`、`description`。出现其他关键字（如 `oneOf`、`pattern`、`$ref`）会被拒绝。

## 校验规则

**错误（阻止安装）**

- 清单结构不合法（缺少必填字段、未知字段、类型错误、命名不合法）。
- 入口文件缺失，或 HTML 超过 256 KiB；单个脚本超过 256 KiB。
- 引用了外部资源（`src`/`href`/`url()`/`@import` 指向 `http(s):` 或 `//`）。
- 使用了 `<base>`、`<iframe>`、`<object>`、`<embed>`、带 `action` 的 `<form>`。
- 出现 `fetch(`、`XMLHttpRequest`、`WebSocket`、`EventSource`、`sendBeacon`、`localStorage`、`sessionStorage`、`indexedDB`、`document.cookie`、`window.open`、`parent.`、`top.` 等字样（HTML 注释中的内容不检查）。
- `sizes` 不是预设尺寸的子集，或 `defaultSize` 不在 `sizes` 里。
- 声明的脚本文件缺失或命名不合法，`schedule` 无法解析，`args`/`ai` 的 Schema 不合法。

**警告（允许安装，但应消除）**

- 在令牌之外写死颜色（hex、rgb、hsl）；`var(--hb-*, #333)` 这类带回退的写法不算。
- 自定义 `font-family`、使用 `box-shadow` 或渐变、字重 500 或 700。
- 缺少 `<main class="hb-card">`、缺少 `<html lang="zh-CN">`、没有处理加载/空/错误状态。

本地也可以用命令行校验目录形式的卡片包：`python -m hermes_board_core.validator <卡片目录…> [--strict]`（`--strict` 时警告也视为失败）。
