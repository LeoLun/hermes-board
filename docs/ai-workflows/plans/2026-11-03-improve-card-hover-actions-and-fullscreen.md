# 卡片悬浮操作与默认卡片全屏适配执行计划

## 前置与假设

- 规格变更：`improve-card-hover-actions-and-fullscreen`。
- 实施分支：`codex/improve-card-hover-actions-and-fullscreen`。
- 实施 worktree：`.worktrees/improve-card-hover-actions-and-fullscreen`。
- 右上角“删除”沿用 `services.removeCard`，仅移出看板并暂停 cron，不删除卡片包、状态和数据。
- 天气默认尺寸和 `cards/default-layout.json` 保持不变，仅新增可选 `12x4`。
- 不新增依赖；全屏继续复用现有 `FullscreenCardDialog`、`CardFrame` 和卡片 entry 文档。

## 执行切片

### 切片 1：悬浮操作组与安全移除

1. 在 `desktop/test/` 增加源码/CSS 结构测试，断言 `CardFrame` 存在统一操作组、全屏在前、删除在后，删除调用 `onRemove`；断言默认隐藏，hover 与 `focus-within` 显示并恢复 pointer events。
2. 运行新测试并确认在当前实现上失败。
3. 修改 `desktop/src/card-frame.js`：把单独的 `.hb-expand` 改成操作组，新增删除按钮；两个按钮阻止 pointer down/click 冒泡并提供卡片标题相关的可访问名称。
4. 修改 `desktop/src/styles.js`：定义操作组、通用按钮、hover/focus-within/reduced-motion 样式，不改变 presentation 模式。
5. 重跑目标测试和全部 Desktop JS 测试。

停止条件：若删除无法复用现有 revision 冲突与 toast 路径，先修复调用链，不能绕过 store 直接请求 API。

### 切片 2：默认卡片操作安全区

1. 在运行时令牌测试中增加安全区变量、非全屏头部避让以及全屏取消避让的断言，确认先失败。
2. 修改 `runtime/card-tokens.css`，定义宿主操作宽度/安全区，并让默认 `.hb-header` 在非全屏环境为右上角留出空间。
3. 检查八张默认卡片的全部 `sizes`；对紧凑尺寸增加必要的换行、收缩或次要操作隐藏规则，确保天气、日历、世界时钟和倒数日的可见操作不落入安全区。
4. 运行 runtime 与默认卡片相关测试。

停止条件：若共享安全区导致某个紧凑尺寸核心操作无法保留，使用该卡片的尺寸规则重新排布，不缩小宿主按钮命中尺寸，也不让按钮重叠。

### 切片 3：天气 12×4

1. 在 `tests/test_default_cards.py` 增加天气声明 `12x4`、默认尺寸仍为 `8x8` 的断言；增加 HTML 中 `12x4` 展示与编辑布局标记的约束，确认先失败。
2. 修改 `cards/weather/card.json` 和原 `cards/weather/index.html`，完成横幅三段布局、编辑态布局及宿主安全区兼容。
3. 运行默认卡片、validator、layout 相关 Python 测试和 JS 约束测试。

停止条件：不修改默认布局；若 `12x4` 与全局预设不一致，则返回规格而不是新增另一尺寸。

### 切片 4：八张默认卡片单 HTML 全屏适配

1. 增加自动约束：八个清单仍只有一个 `entry`，八个 `index.html` 均包含 `data-size="fullscreen"` 规则；已有 fullscreen env 测试继续验证 resize 只更新环境。
2. 逐张在原 HTML 中增加全屏布局：
   - 时钟、倒数日限制核心数字最大宽度/字号并居中；
   - 天气、世界时钟、日历使用受控宽度或多列布局；
   - 番茄钟宽屏并排、低宽/低高退化为上下布局；
   - 便签、待办让内容区独立滚动并保持输入/操作可达。
3. 在共享令牌中补充全屏 padding、最大内容宽度与滚动基线，但不改变非全屏既有视觉语义。
4. 运行全部 JS 与默认卡片 Python 测试。

停止条件：不得创建第二份 HTML、`fullscreenEntry` 或 resize 时重建 iframe；若布局只能靠重新加载生效，先修复运行时环境属性更新。

### 切片 5：视觉验证、打包与收尾

1. 构建 Desktop bundle，在可用的静态/浏览器渲染路径中检查紧凑尺寸、默认尺寸、天气 `12x4` 和至少三组全屏 viewport；无法自动渲染的项目记录明确的人工检查路径。
2. 运行 `pnpm test:js`、完整可用 Python 测试、`pnpm build`、`pnpm check` 和 `git diff --check`。
3. 按 OpenSpec 成功标准审查最终 diff，修复遗漏后勾选 `tasks.md`。
4. 使用 `workflow-close` 归档变更到 `docs/ai-workflows/openspec/changes/archive/2026-11-03-improve-card-hover-actions-and-fullscreen/`，保留实施计划作为历史记录。

## 基线验证

- worktree 创建后运行 `pnpm test:js`。
- 运行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`；若仅因仓库已知的 FastAPI 环境缺失失败，必须再运行与本变更相关且不依赖 FastAPI 的测试并记录该环境限制。
- 基线出现与已知环境限制无关的失败时停止实现。

## 最终验收重点

- 操作组只有在 hover/焦点时可见，全屏左、删除右，键盘和 reduced-motion 行为完整。
- 删除走现有可恢复移除链路。
- 默认卡片内部操作与宿主按钮无命中区域重叠。
- 天气 `12x4` 的展示态与编辑态信息完整。
- 八张默认卡片只使用原 HTML，fullscreen resize 不重载且内容自适应。

