# 项目说明：hermes-blueprint

本仓库用于开发 Hermes 插件 **`hermes-board`**（Hermes 看板）。它是一个统一插件包：同一个仓库同时提供 Agent 端（Python 工具与技能）、远程后端 API（`dashboard/plugin_api.py`）和 Hermes Desktop 端（`desktop/plugin.js`）。

## 部署拓扑

- **本机**：macOS 上的 Hermes Desktop（`/Applications/Hermes.app`），负责渲染看板页面和卡片。Desktop 端插件安装在本机 `$HERMES_HOME/desktop-plugins/hermes-board/`。
- **远程**：Linux 主机上的 `hermes serve`。卡片包、数据脚本、SQLite 数据、布局 DSL 和 cron 任务都在远程，以远程数据为准。Desktop 只能通过当前连接网关的插件作用域 REST（`ctx.rest` → `/api/plugins/hermes-board/*`）访问它们。
- 远程主机的插件目录不会自动同步到 Desktop。安装方式与参考项目 [hermes-bill-plugin](https://github.com/LeoLun/hermes-bill-plugin) 一致：在远程执行 `hermes plugins install` 和 `enable`，在 Desktop 中通过 Capabilities → Plugins → Install from Git 勾选 Desktop 目标。

## 技术约束（来自 Hermes 0.22.x 本机源码与文档）

- Desktop 插件是单个 ESM 文件，加载时不经编译。它只能导入 `@hermes/plugin-sdk`、`react`、`react/jsx-runtime`，不能写 JSX 语法。仓库内可以分模块编写，再用 esbuild 打包成 `desktop/plugin.js` 并提交。
- Desktop 插件拥有完整 App 权限，因此外部 HTML 必须放进 SDK 的 `SandboxedFrame`（只接受 `data:`/`http(s):`，origin 不透明，默认 `allow-scripts`）。
- Python 后端只有在远程 `config.yaml` 的 `plugins.enabled` 中列出后才会被导入，路由挂载在 `/api/plugins/hermes-board/`。
- 插件持久数据必须放在 `<HERMES_HOME>/plugin-data/<name>/`，不能放在会被删除或更新的安装目录里。
- cron 的 no-agent 脚本必须位于 `$HERMES_HOME/scripts/` 内，允许子目录，最小调度间隔为 1 分钟。
- `ctx.socket` 在 OAuth 远程上不可用，所以所有实时更新都必须有轮询兜底。

## 技术栈与约定

- Python ≥ 3.11（Hermes venv 为 3.12），只用标准库、FastAPI（宿主提供）和 sqlite3；测试用 `unittest`。
- Desktop 和卡片运行时使用原生 ES2022 JavaScript（不用 TypeScript 编译、不用 JSX），用 esbuild 打包，用 Node ≥ 20 的 `node --test` 做纯逻辑测试。
- 文档、技能、界面文案默认用简体中文。
- OpenSpec 的权威位置是 `docs/ai-workflows/openspec/`，仓库根目录的 `openspec` 只是兼容软链接。执行计划放在 `docs/ai-workflows/plans/YYYY-MM-DD-<change>.md`。

## 命名

| 对象 | 名称 |
|---|---|
| 插件 id / 包名 | `hermes-board` |
| 侧边栏标签 / 路由 | “看板” / `/hermes-board` |
| Python 内部包 | `hermes_board_core` |
| Agent 工具 / 工具集 | `board_manage` / `hermes_board` |
| 技能 | `hermes-board:card-author` |
| 卡片运行时全局对象 | `window.HermesCard` |
| CSS 前缀 / 设计令牌 | `hb-` / `--hb-*` |
| 事件 | `plugin.hermes-board.<event>` |
