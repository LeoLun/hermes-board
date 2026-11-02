# 卡片设计标准（基于 Apple DESIGN.md）

运行时会在每张卡片的 `<head>` 最前面注入设计令牌和组件类，卡片只需引用它们。目标是所有卡片风格一致：干净的表面、克制的强调色、清晰的数字层级。

## 令牌

颜色一律通过 CSS 变量引用，不要写死 hex、rgb、hsl。主题切换（浅色/深色）由宿主完成，变量会自动变化。

| 变量 | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--hb-surface` | `#ffffff` | `#272729` | 卡片表面 |
| `--hb-surface-2` | `#fafafc` | `#2a2a2c` | 内部浅色块（Pearl） |
| `--hb-ink` | `#1d1d1f` | `#ffffff` | 主文字、主要数字 |
| `--hb-ink-2` | `#333333` | `#cccccc` | 次要文字 |
| `--hb-ink-muted` | `#7a7a7a` | `#7a7a7a` | 说明、单位、时间 |
| `--hb-hairline` | `rgba(0,0,0,.08)` | `rgba(255,255,255,.08)` | 发丝线、描边 |
| `--hb-divider` | `#f0f0f0` | 随主题 | 列表分隔线 |
| `--hb-accent` | `#0066cc` | `#2997ff` | 唯一强调色：链接、主按钮、图表主系列 |
| `--hb-focus` | `#0071e3` | 随主题 | 焦点环 |
| `--hb-positive` | `#34c759` | `#30d158` | 状态：正常 |
| `--hb-warning` | `#ff9500` | `#ff9f0a` | 状态：注意 |
| `--hb-critical` | `#ff3b30` | `#ff453a` | 状态：异常 |

状态色**只能用于表达状态**（例如温度过高、节点不可用），不能用作装饰。图表的主系列用强调色，其他系列用灰阶（`--hb-ink-2`、`--hb-ink-muted`）。

## 字体与字号

- 字体栈由运行时提供（`-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", system-ui, sans-serif`），**不要自定义 `font-family`**。
- 数字一律用 `tabular-nums`（下列字号类已包含）。
- 字重只用 300、400、600，不用 500 和 700。
- 17px 以上的字号使用负字距（字号类已处理）。

| 类 | 字号 / 字重 / 行高 | 用途 |
|---|---|---|
| `hb-metric-lg` | 40 / 600 / 1.1 | 大卡片的核心数字 |
| `hb-metric` | 34 / 600 / 1.1，字距 -0.374px | 核心数字 |
| `hb-metric-sm` | 21 / 600 / 1.19 | 次级数字 |
| `hb-title` | 14 / 600 / 1.29，字距 -0.224px | 卡片标题 |
| `hb-body` | 14 / 400 / 1.43 | 正文 |
| `hb-body-lg` | 17 / 400 / 1.47，字距 -0.374px | 大号正文 |
| `hb-fine` | 12 / 400 / 1.33 | 说明、单位、时间 |
| `hb-micro` | 10 / 400 / 1.3 | 坐标轴、角标 |

## 间距与圆角

- 以 8px 为基准（4、8、12、16、24）。
- 卡片内边距由 `hb-card` 自动设置：宽度不超过 6 格时 16px，8 格及以上时 24px。
- 卡片圆角 18px 由宿主外框裁切，卡片自身不需要设置。内部浅色块（`hb-well`）11px，工具按钮 8px，主要按钮、胶囊标签和输入框用全圆角。

## 层次

卡片内部**不用阴影、不用渐变、不加装饰性边框**。层次只靠表面色（`--hb-surface` 与 `--hb-surface-2`）和发丝线（`--hb-hairline`）区分。

## 组件类

| 类 | 说明 |
|---|---|
| `hb-card` | 根元素，必须是 `<main class="hb-card">` |
| `hb-header` | 标题行（标题在左，操作或更新时间在右） |
| `hb-title` | 卡片标题 |
| `hb-btn` | 主要按钮：强调色、全圆角 |
| `hb-btn--secondary` | 次要按钮：描边、全圆角 |
| `hb-btn--utility` | 工具按钮：8px 圆角，图标或短文字 |
| `hb-input` | 输入框：全圆角 |
| `hb-chip` | 胶囊标签 |
| `hb-list` / `hb-row` | 列表和行（行间用分隔线） |
| `hb-well` | 内部浅色块（11px 圆角，`--hb-surface-2`） |
| `hb-state` | 加载、空、错误三态容器，配合 `HermesCard.ui.state` 使用 |
| `hb-updated` | “更新于 14:32”，配合 `HermesCard.ui.updated` 使用 |

交互：按下时 `scale(.95)`，焦点环为 2px `--hb-focus`；动效时长 200ms，并遵守 `prefers-reduced-motion`（组件类已处理）。

## 状态

每张取数卡片都要处理三种状态：

- **加载**：数据尚未返回时显示 `HermesCard.ui.state(el, 'loading')`。
- **空**：脚本尚未运行过或没有数据时显示 `HermesCard.ui.state(el, 'empty', '暂无数据，点击刷新')`。
- **错误**：读取失败或运行失败时显示 `HermesCard.ui.state(el, 'error', err.message)`，并给出重试入口。
- 数据正常时调用 `HermesCard.ui.state(el, 'ready')` 隐藏状态层，并用 `HermesCard.ui.updated(el, updatedAt)` 显示更新时间。

## 尺寸适配

运行时会在 `<html>` 上设置 `data-size="6x4"`、`data-w`、`data-h`、`data-theme`，尺寸变化时同步更新并触发 `resize` 事件。用属性选择器为不同尺寸调整布局，例如：

```css
html[data-size="4x4"] .forecast { display: none; }
html[data-w="8"] .grid { grid-template-columns: repeat(3, 1fr); }
```

卡片在宿主的全屏弹窗中显示时，运行时设置 `data-size="fullscreen"`、`data-w="24"`、`data-h="16"`。可用该选择器提供宽屏布局；全屏不会改变卡片在看板中的持久化尺寸。

- 卡片在声明的**每一种尺寸**下都不能出现整体滚动条，内容要按尺寸取舍。
- 列表只允许在高度不少于 6 格时内部滚动。
- 一格的实际像素随窗口宽度变化（24 到 72px），用 `HermesCard.env.pixel` 或百分比布局，不要假设固定像素。

## 图表与格式化

- 图表用 `HermesCard.chart.line`、`sparkline`、`bar`、`ring`（SVG，自动使用令牌颜色并跟随主题），不要引入外部图表库。
- 数字、百分比、字节、时长、相对时间用 `HermesCard.fmt` 格式化（中文格式），保证各卡片一致。
