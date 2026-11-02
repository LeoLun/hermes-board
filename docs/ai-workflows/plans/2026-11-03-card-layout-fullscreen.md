# 卡片布局与全屏实现计划

## 基线

- 分支：`codex/card-layout-fullscreen`
- worktree：`.worktrees/card-layout-fullscreen`
- `pnpm test:js`：85/85 通过。
- Python：除 `tests/test_api.py` 因环境缺少 `fastapi` 无法导入外，其余 110 项通过。

## 执行步骤

1. **尺寸预设**
   - 先更新常量测试，期望包含 `12x4`、`24x4`，并增加 24×4 边界布局用例。
   - 修改 `shared/constants.json`，同步作者参考文档。
   - 运行 constants、validator、layout 与 JS layout 测试。

2. **整理防抖**
   - 增加可测试的 arranging 标记和稳定 scrollbar CSS 断言。
   - 页面提升 `arranging` 状态，由整理按钮在异步操作前后设置。
   - 看板节点带 `data-arranging`，CSS 在该状态关闭几何 transition。

3. **全屏宿主**
   - 抽出/导出全屏逻辑环境计算，先写像素尺寸测试。
   - 扩展 `CardFrame`：可注入 env size/pixel、关闭注册和编辑控件，增加放大按钮。
   - 新建 `FullscreenCardDialog`，测量内容区并挂载展示模式 CardFrame。
   - 在 `BoardPage` 管理打开/关闭状态，不改 store/layout。

4. **收尾验证**
   - 运行 `pnpm test:js`。
   - 运行不依赖 FastAPI 的 Python 相关测试，以及可用时的完整 Python 套件。
   - 运行 `pnpm build` 和 `pnpm check`，确认生成的 `desktop/plugin.js` 与源码一致。
   - 更新 OpenSpec tasks 勾选状态并检查 diff。

## 停止条件

- 若 SDK Dialog 无法提供所需尺寸或焦点行为，回到规格决定是否使用自建模态层。
- 若全屏实例会覆盖原卡片注册或导致重复副作用，必须先隔离注册与生命周期，不能以布局持久化模拟全屏。
