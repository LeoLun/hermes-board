# claude-card-style-and-header 执行计划

## 前置与假设

- 实施工作树：`/Users/liujinglun/ai-app/manus/hermes-blueprint/.worktrees/claude-card-style`
- 分支：`codex/claude-card-style`
- JS 基线：85/85 通过。
- 与变更相关的 Python 基线：默认卡片 10/10、模板 3/3、校验器 19/19 通过。
- 完整 Python discover 在当前系统 Python 下因未安装 `fastapi` 无法导入 `test_api.py`；这是环境依赖限制，收尾时会明确报告。

## 执行切片

### 切片 1：页头回归与移除

1. 在 `desktop/test/` 增加源码约束测试：断言 `desktop/src/board-page.js` 不得包含 `WorkspacePageHeaderControl`/`HeaderControl`，且必须在空状态渲染 `AddCardButton`。
2. 运行新测试并确认先失败。
3. 修改 `desktop/src/board-page.js`：去掉 SDK 命名空间和 `Header`，在空看板 `Center.actions` 中渲染 `AddCardButton`，不在页面根节点渲染页头。
4. 如命令面板没有添加选择器，用最小可控状态补充命令；否则仅保留现有 reload 命令。
5. 重跑新测试与全部 Desktop JS 测试。

停止条件：若移除页头后没有可实现的非页头添加入口，返回 OpenSpec 调整范围，不把页头偷偷改为另一种 Tab。

### 切片 2：Claude 令牌与组件

1. 增加 `runtime/test/design-tokens.test.mjs`，读取 CSS 并检查浅色/深色关键色值、display/body 字体、8px 控件圆角、12px 内容圆角和无蓝色主强调。
2. 运行新测试确认先失败。
3. 按 `design.md` 映射修改 `runtime/card-tokens.css`，保持现有公共类名和卡片兼容性。
4. 重跑运行时 JS 测试。

停止条件：若现有卡片依赖被删除的令牌/类，保留兼容别名而不大规模重写卡片。

### 切片 3：默认卡片和生成规范

1. 扫描 `cards/*/index.html` 和 `skills/card-author/templates/basic-card/index.html` 的局部 CSS，找出与 Claude 字重、形状或色彩语义冲突的规则。
2. 只做必要的局部修正；不改卡片数据与交互 JavaScript。
3. 重写 `skills/card-author/references/design-standard.md`，同步 `skills/card-author/SKILL.md` 的基准描述。
4. 运行默认卡片、模板和校验器 Python 测试。

### 切片 4：打包和收尾

1. 运行 `pnpm build`，更新提交的 `desktop/plugin.js`。
2. 运行 `pnpm test:js`、相关 Python discover 命令和 `pnpm check`。
3. 审查 `git diff --check`、实现 diff 与 OpenSpec 验收条目。
4. 更新 `tasks.md` 完成状态，按 `workflow-close` 执行最终验证并归档变更。
