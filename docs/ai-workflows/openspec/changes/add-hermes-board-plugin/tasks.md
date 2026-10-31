# 任务清单：add-hermes-board-plugin

状态：规格已确认（2026-10-31 16:10）。执行计划见 [docs/ai-workflows/plans/2026-10-31-add-hermes-board-plugin.md](../../../plans/2026-10-31-add-hermes-board-plugin.md)；用户已授权实施（2026-10-31 16:17），在工作树 `.worktrees/add-hermes-board-plugin` 中进行。

## 0. 审批与前置

- [x] 0.1 用户审阅并定稿 proposal、design 和 7 份能力规格。
- [x] 0.2 用 workflow-plan 生成 `docs/ai-workflows/plans/2026-10-31-add-hermes-board-plugin.md`。
- [x] 0.3 建立基线：`.gitignore`、`.agents/skills/`、OpenSpec 文档和 `openspec` 软链接已作为初始提交（2026-10-31）。隔离工作树仍由 workflow-worktree 在实施前创建。
- [x] 0.4 记录开发环境：本机 Hermes 0.22.2、Hermes venv Python 3.12、Node ≥ 20；准备一台远程 Linux 验证主机，或用本机 `hermes serve` 先替代，最终验收必须在 Linux 上做。（已记录：Hermes 0.22.2、venv Python 3.12、Node 26.10、pnpm 9.15；远程 Linux 主机待用户提供，目前用本机替代）

## 1. 技术验证（先做，任一项不成立就回到 workflow-spec）

- [ ] 1.1 V1：最小 Desktop 插件里用 `SandboxedFrame` 加载 base64 `data:` 文档，验证注入的 meta CSP（`fetch` 被拦截）、双向 postMessage，以及用 `event.source` 加令牌做认证；测量 20 个 iframe 的内存占用。（进展：无头 Chromium 中已验证 data: 文档、meta CSP 拦截 fetch、双向 postMessage、自导航二次 load；17:14 又用真实运行时 + bridge 在无头 Chromium 做了端到端验证（.work/e2e/，CDP 驱动），全部通过；Desktop 内 SandboxedFrame 与内存测量待 G3 授权）
- [x] 1.2 V2：在插件进程内调用 `cron.jobs` 的创建、更新、删除、暂停、恢复接口；确认 profile 隔离，以及 `scripts/hermes-board/<card>/x.py` 这种子目录脚本能按 no-agent 方式运行；确认 SDK 能根据路径反推 `HERMES_HOME`。
- [ ] 1.3 V3：在 `register(ctx)` 中保存 `ctx.llm`，确认 `plugin_api.py` 能调用 `complete_structured`。（待 G3 授权；单元测试已用假 llm 覆盖）
- [ ] 1.4 确认 `WorkspacePageHeaderControl`、`useTheme().resolvedMode`、`ctx.setTimeout`、`ctx.os.notify` 在目标版本中可用，并确定 `requires_hermes` 的最低版本。（`requires_hermes: ">=0.22.2"` 已确定；Desktop 侧接口待 V1 真机确认）

## 2. 仓库骨架与构建

- [x] 2.1 `plugin.yaml`、`__init__.py`、`dashboard/manifest.json`、`dashboard/plugin_api.py`（只提供 `/health`）。
- [ ] 2.2 `package.json`（esbuild，以及 `build`、`test:js`、`check` 脚本），把 `desktop/src` 和 `runtime/` 打包成 `desktop/plugin.js`（运行时以文本形式内联）。
- [ ] 2.3 测试框架：Python `unittest`（临时 `HERMES_HOME`）、`node --test`、共用的 `tests/fixtures/layout-cases.json`。
- [ ] 2.4 `.gitignore`；`README.md` 安装章节，包含远程和 Desktop 两部分。

## 3. 服务端存储与布局（specs: board-layout-dsl、card-data-scripts）

- [x] 3.1 `paths.py`：基于 `plugin_data_dir` 和 `scripts` 的路径解析、命名规则校验、防止路径穿越。
- [x] 3.2 `store.py`：SQLite 建表与迁移、WAL、各类读写接口、大小限制、分批清理、`changes` 流水。
- [x] 3.3 `layout.py`：DSL 校验、迁移、原子写入、`revision` 和 409 冲突、首次适配放置、不可用卡片占位。
- [x] 3.4 对应的单元测试，覆盖 spec 中的全部场景。

## 4. 卡片包（spec: card-package）

- [x] 4.1 `validator.py`：清单 Schema、HTML 安全规则（错误）、设计规则（警告）、`schedule` 解析、`args`/`ai` Schema 子集。
- [x] 4.2 `cards.py`：注册表扫描、`revision` 递增、在安装锁下两侧原子安装、失败回滚（包括 cron）、删除到 trash。
- [x] 4.3 SDK 同步（按内容哈希）。
- [x] 4.4 单元测试：路径穿越、外部资源、回滚、未确认的删除等场景。

## 5. 脚本执行与 cron（spec: card-data-scripts）

- [x] 5.1 `sdk/hermes_board_sdk.py`：路径推断、data、series、state、progress、result，以及 cron 触发时自己写运行记录且不输出。
- [x] 5.2 `runner.py`：参数校验与临时文件传参、最小间隔、单飞、全局并发 4、超时后杀进程组、输出截断、`.sh` 结果行解析、`run.finished` 事件。
- [x] 5.3 `cron_sync.py`：cron 适配层与可用性探测、绑定表、安装/删除/移出/放回时的同步、全量对账与清理孤儿任务。
- [x] 5.4 单元测试（用假 cron 模块）以及一个真实子进程的集成测试。（含 tests/host/test_cron_host.py：设置 HERMES_AGENT_ROOT 时用真实 cron 模块验证，已通过）

## 6. REST API、AI 与事件（specs: card-data-scripts、card-runtime-bridge）

- [x] 6.1 `plugin_api.py`：实现 design.md 第 9 节的全部接口，统一错误格式，加 `no-store`。
- [x] 6.2 `ai.py`：`ctx.llm` 句柄、输入输出校验、运行记录、不可用时降级。（真机调用 complete_structured 待 V3）
- [x] 6.3 `events.py`：`broadcast_plugin_event` 封装（layout/card/run）。
- [x] 6.4 `init.py`：在 `.init.lock` 保护下做幂等首次初始化（与第 10 节联调）。
- [x] 6.5 API 测试（FastAPI `TestClient`）。

## 7. Agent 工具与技能（spec: card-authoring-agent）

- [x] 7.1 `board_manage` 的 9 个操作，结构化错误。
- [x] 7.2 `skills/card-author/SKILL.md` 和 4 份参考文档（design-standard、manifest、runtime-api、script-sdk）。
- [x] 7.3 `templates/basic-card/`（清单、HTML、脚本），并确认它能通过校验。
- [ ] 7.4 工具测试；在真实对话中创建一张卡片，作为验收（见 11.3）。

## 8. 卡片运行时与设计标准（specs: card-runtime-bridge、card-package）

- [x] 8.1 `runtime/card-tokens.css`：浅色和深色令牌、字号阶梯、组件类、减少动效的适配。
- [x] 8.2 `runtime/card-runtime.js`：握手、请求和响应、事件、`html[data-*]`、右键转发、`run` 的 wait 封装、`fmt`、`chart`（line/sparkline/bar/ring）、`ui.state`。
- [x] 8.3 JS 测试：协议编解码、格式化函数、图表输出的 SVG 结构。

## 9. Desktop 插件（spec: board-desktop、card-runtime-bridge）

- [ ] 9.1 注册内容：路由、侧边栏、命令面板、头部控件（带特性检测）。
- [ ] 9.2 API 客户端与轮询器（5 秒/30 秒，事件触发补拉，reset 处理），`apiVersion` 兼容检查。
- [ ] 9.3 `html-transform`（注入和 base64）与 `card-host`（SandboxedFrame、令牌、10 秒超时、自导航时重建、文档缓存、视口内才挂载）。
- [ ] 9.4 `bridge`：白名单、卡片作用域、参数校验、限流、订阅分发、notify、remind、openExternal、contextmenu。
- [ ] 9.5 `grid`：尺寸计算与渲染、主题、错误和空状态、断开连接标记。
- [ ] 9.6 `gestures`：悬停手柄、移动、调整（预设吸附、固定角）、推挤、Esc 取消、手势期间屏蔽 iframe 指针事件、键盘操作。
- [ ] 9.7 `arrange`：三种候选顺序的首次适配、评分、动画、撤销。
- [ ] 9.8 “添加卡片”弹层、卡片菜单、“最近运行”对话框、409 冲突时重放。
- [ ] 9.9 JS 测试：吸附、推挤、整理、冲突重放（共用测试用例）。

## 10. 默认卡片（spec: default-cards）

- [ ] 10.1 天气（Open-Meteo 脚本，默认城市北京，可修改城市）。
- [ ] 10.2 时钟、世界时钟、日历、倒数日。
- [ ] 10.3 番茄钟（时间戳状态，配合 `ui.remind`）。
- [ ] 10.4 便签、待办。
- [ ] 10.5 默认布局（24×16 无缝铺满）；测试：8 张卡片校验无错误也无设计警告，布局覆盖率为 100%，初始化幂等。

## 11. 验收与收尾

- [ ] 11.1 全量自动化测试和打包检查通过。
- [ ] 11.2 远程 Linux：`hermes plugins install` 和 `enable`，重启 `hermes serve`；Desktop：Install from Git 并勾选 Desktop 目标。按 README 人工清单逐项验证（交互、主题、cron 页面中的任务、OAuth 远程下的轮询、越权调用被拒绝）。
- [ ] 11.3 通过对话让 Hermes 创建一张带定时脚本和按钮操作的新卡片，确认全程不需要手动改文件。
- [ ] 11.4 用 workflow-close 做评审、最终验证和 OpenSpec 归档。
