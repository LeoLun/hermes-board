---
name: card-author
description: 通过对话为 Hermes 看板（hermes-board）创建或修改卡片。用于用户要求“做一个看板卡片”“在看板上显示……”“修改某张卡片”时：澄清需求，起草 card.json、单文件 index.html 和数据脚本，用 board_manage 校验、保存、自测，并配置 cron 定时刷新。
version: 1.0.0
---
# 看板卡片创作

看板上的每张卡片是一个**卡片包**：清单 `card.json`、单文件 `index.html`，以及可选的数据脚本 `scripts/*.py|*.sh`。卡片包只能通过 `board_manage` 工具安装到远程，不要手工写入 `plugin-data/hermes-board/` 或 `scripts/hermes-board/` 目录，也不要直接改 `board.json` 或 `board.sqlite3`。

## 先读参考文档

动手前，用 `skill_view` 读取本技能的参考文件（`name` 为 `hermes-board:card-author`）：

| 文件 | 内容 |
|---|---|
| `references/manifest.md` | `card.json` 的字段、命名规则、尺寸、调度格式、Schema 子集、校验规则 |
| `references/design-standard.md` | 设计令牌、字号阶梯、间距圆角、组件类、尺寸适配，基于 Claude DESIGN.md |
| `references/runtime-api.md` | 卡片 HTML 中可用的 `window.HermesCard` 接口 |
| `references/script-sdk.md` | 数据脚本 SDK（`hermes_board_sdk.Card`）、运行方式、凭据与权限 |
| `templates/basic-card/card.json`、`templates/basic-card/index.html`、`templates/basic-card/scripts/fetch.py` | 可直接改写的起始模板，能通过严格校验 |

修改已有卡片时，先用 `board_manage {action:"get", card}` 拿到当前的清单、HTML 和脚本，在其基础上修改。

## 工作流程

1. **澄清需求**：要展示什么数据、数据从哪里来、多久刷新、卡片上需要哪些操作按钮，以及展示尺寸（从 `4x4`、`4x6`、`6x4`、`6x6`、`8x4`、`8x6`、`8x8`、`12x6`、`12x8` 里选 1 到 4 种，并指定默认尺寸）。信息不足且无法合理推断时，提一个简洁的问题。
2. **起草卡片包**：从 `templates/basic-card/` 开始。
   - 取数一律放在脚本里：卡片 HTML 不能联网，也不能引用任何外部资源。
   - 脚本把结果写入数据集（最新快照）或序列（时间序列），卡片通过 `HermesCard.data` / `HermesCard.series` 读取。
   - 需要定时刷新的脚本写 `schedule`（如 `every 30m`），由 Hermes 原生 cron 运行；需要卡片按钮触发的脚本写 `callable: true`，并用 `args` 声明参数。
   - 需要 AI 判断时（例如从测速结果里选最优节点），在清单的 `ai` 中声明任务，卡片用 `HermesCard.ai.invoke` 调用，结果必须符合 `outputSchema`。
   - 卡片 id 用小写短横线命名，例如 `server-status`。
3. **校验**：`board_manage {action:"validate", package}`。`valid` 为 false 时按 `errors` 逐条修正；`warnings` 是设计规范提示，应尽量全部消除（通常是写死了颜色、自定义了字体、用了阴影或渐变、字重不是 300/400/500/600、缺少加载/空/错误状态）。
4. **保存**：`board_manage {action:"save", package}`。新卡片会自动放到看板的首个空位；指定位置时传 `place: {x, y, size}`。更新已有卡片必须传 `replace: true`，卡片保留原位置。保存后会在后台运行声明了 `runOnInstall` 的脚本。
5. **自测**：
   - `board_manage {action:"run", card, script, args}` 运行脚本，检查 `status`、`result`、`stdoutTail`、`stderrTail`、`error`。
   - `board_manage {action:"data", card, kind:"data"|"series"|"state"|"runs", name?}` 确认数据已正确写入。
   - 失败时修正脚本，再用 `save` + `replace: true` 更新。
6. **告知用户**：说明卡片已放到“看板”页面的位置、刷新频率和可用操作。不要把脚本源码整段贴给用户，除非用户要求。

## 卡片包格式

```json
{
  "manifest": { "schema": "hermes-board/card@1", "id": "...", "...": "见 references/manifest.md" },
  "html": "<!doctype html>…完整的 index.html…",
  "scripts": { "fetch.py": "…脚本源码…" }
}
```

## 硬性规则

- HTML 中禁止：外部 `src`/`href`/`url()`/`@import`（指向 `http(s):` 或 `//`），`<base>`、`<iframe>`、`<object>`、`<embed>`、带 `action` 的 `<form>`，以及 `fetch(`、`XMLHttpRequest`、`WebSocket`、`EventSource`、`sendBeacon`、`localStorage`、`sessionStorage`、`indexedDB`、`document.cookie`、`window.open`、`parent.`、`top.`。需要图表时用 `HermesCard.chart`，需要持久化时用 `HermesCard.state`，需要打开网页时用 `HermesCard.ui.openExternal`。
- 卡片运行在严格 CSP 的沙箱 iframe 中，就算绕过了校验也无法联网；校验只是为了让你在安装前尽早发现问题。
- 凭据（API Key、Token）不要写进卡片文件。请用户在远程 Hermes 的 `terminal.env_passthrough` 中放行对应环境变量，脚本通过 `os.environ` 读取。
- 需要特权的操作（例如重启系统服务、修改代理配置）由用户在远程机器上自行配置权限（如 sudoers 中的特定命令），卡片脚本只调用已授权的命令。不要在脚本里尝试提权，也不要让用户把密码交给你。
- 读取其他插件的数据时只读打开，例如 `sqlite3.connect("file:...?mode=ro", uri=True)`，不要写入别人的数据库。

## 需要 Agent 定期决策的场景

卡片内的 `ai.invoke` 只在用户打开看板并点击时运行。如果用户要求“自动选择并切换”这类无人值守的决策，额外用 Hermes cron 创建一个 **agent 任务**（不是 no-agent 脚本任务），在提示词中让 Agent 调用 `board_manage {action:"run"}` 测试、读取 `board_manage {action:"data"}` 的结果、做出判断，再调用切换脚本。把这个 cron 任务的用途和频率告诉用户。

## 移除卡片

`board_manage {action:"remove", card, confirm:true}` 只把卡片从看板上移除并暂停其定时任务；加上 `deletePackage: true` 会删除卡片包、cron 任务和全部数据（文件会移到 trash）。删除前必须征得用户明确同意。内置默认卡片可用 `restore_default` 恢复。
