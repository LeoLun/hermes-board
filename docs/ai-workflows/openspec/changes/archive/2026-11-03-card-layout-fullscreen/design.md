# 设计：稳定整理、横幅尺寸与全屏卡片

## 1. 自动整理

保留现有纯函数 `arrange()`，不改变后端布局语义。桌面端增加两层显示保护：

1. `.hb-scroll` 使用稳定的 scrollbar gutter，阻止整理前后因纵向滚动条切换而改变 `clientWidth`。
2. 页面持有 `arranging` 状态；从点击开始到 `store.arrange()` 完成期间，在看板节点标记 `data-arranging`，CSS 关闭卡片的 left/top/width/height transition。

这比修改整理算法风险更小，因为算法已有共享用例验证且输出不重叠；问题发生在结果渲染阶段。

## 2. 新尺寸

继续以 `shared/constants.json` 为 Python 与 JavaScript 的唯一事实源，在预设顺序中加入 `12x4`、`24x4`。后端校验、前端吸附与键盘尺寸切换将自动读取新列表。同步更新作者文档与常量测试。

## 3. 全屏卡片

新增 `FullscreenCardDialog`：

- 用 SDK `Dialog` 构建接近工作区大小的模态容器；
- 复用 `CardFrame` 的沙箱、加载、Bridge 和订阅逻辑；
- 给 `CardFrame` 增加 presentation 模式，可注入实际 pixel 和逻辑 size，并隐藏拖拽/缩放控件；
- 全屏逻辑尺寸为 `{w:24,h:16,label:"fullscreen"}`，实际像素由 `ResizeObserver` 测量弹窗主体；
- 全屏实例不调用 `services.registerFrame`，避免覆盖看板原实例的注册项；
- 看板页面只保存当前全屏 `cardId`，不进入 store，不触发 API 布局写入。

## 4. 交互与可访问性

放大按钮使用 `button` 和明确的 `aria-label`，位于卡片右上角并在 hover、focus-within 时可见。弹窗沿用 SDK 的焦点管理、Esc 关闭与遮罩行为。

## 5. 验证

- 常量与布局测试覆盖新预设和 24 列边界。
- UI 结构测试覆盖全屏环境尺寸辅助函数与防抖 CSS 标记。
- 运行完整 JS 测试、相关 Python 测试、桌面构建和 bundle 一致性检查。
