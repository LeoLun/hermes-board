# 设计：移除看板页头并迁移到 Claude 卡片风格

## 1. 页头处理

`desktop/src/board-page.js` 不再导入或检测 `WorkspacePageHeaderControl`，也不再渲染 `Header`。为避免能力丢失：

- 空看板中渲染内联的 `AddCardButton`。
- “看板：重新加载”命令保留。
- 非空看板的新卡片仍可由对话创建，也可在命令面板中打开添加选择器；若现有命令未暴露选择器，在本变更内补充一条。

## 2. Claude 令牌映射

保留现有 `--hb-*` 名称以兼容已安装卡片，仅改变语义值并增加字体/圆角令牌。

| Hermes 令牌 | Claude 浅色 | Claude 深色 | 语义 |
|---|---:|---:|---|
| `--hb-surface` | `#faf9f5` | `#181715` | 卡片画布 |
| `--hb-surface-2` | `#efe9de` | `#252320` | 内部内容面 |
| `--hb-ink` | `#141413` | `#faf9f5` | 主文字 |
| `--hb-ink-2` | `#3d3d3a` | `#d8d2c8` | 正文/次文字 |
| `--hb-ink-muted` | `#6c6a64` | `#a09d96` | 辅助文字 |
| `--hb-hairline` | `#e6dfd8` | `#3a3732` | 输入与边框 |
| `--hb-divider` | `#ebe6df` | `#35322e` | 列表分隔 |
| `--hb-accent` | `#cc785c` | `#cc785c` | 主操作/图表 |
| `--hb-accent-active` | `#a9583e` | `#e08b70` | 按下状态 |
| `--hb-on-accent` | `#ffffff` | `#ffffff` | 强调面文字 |
| `--hb-focus` | `#cc785c` | `#e08b70` | 焦点 |

状态色使用 Claude 文档的 success `#5db872`、warning `#d4a017`、error `#c64545`，深色下只做必要的亮度调整。

## 3. 字体与层级

- `--hb-font-display`: `"Tiempos Headline", "Cormorant Garamond", "EB Garamond", Georgia, "Songti SC", serif`。
- `--hb-font-body`: Inter, `-apple-system`, BlinkMacSystemFont, `"Segoe UI"`, `"PingFang SC"`, sans-serif。
- `--hb-font-code`: `"JetBrains Mono"`, `SFMono-Regular`, Consolas, monospace。
- `.hb-title` 使用展示字体、16px/400/1.3，负字距。
- `.hb-metric*` 使用展示字体、400 字重和 `tabular-nums`，避免 Claude 风格中不适合的粗黑大数字。
- 正文类使用人文无衬线字体，标签/按钮可使用 500，正文 400。

## 4. 形状与组件

- `--hb-radius-control: 8px`，用于按钮、输入框和工具控件。
- `--hb-radius-card: 12px`，用于 `hb-well` 和内容面。
- `--hb-radius-pill: 9999px`，仅用于标签和语义上的胶囊。
- 主按钮为珊瑚底色、8px 圆角、40px 可用高度目标；小卡片中可保持紧凑高度，但视觉语义不变。
- 次按钮使用卡片画布和 hairline，不使用珊瑚描边填满所有操作。
- 焦点环为 2px 珊瑚边框加低透明外环，保证键盘可达性。
- 按下反馈以颜色变化为主，去掉 Apple 式 `scale(.95)`。

## 5. 生成约束

`skills/card-author/references/design-standard.md` 将用中文重写为 Claude 卡片标准，保留尺寸、状态、图表和格式化约束，并更新：

- 颜色与深浅主题令牌表。
- 展示/正文字体分工和可用回退字体。
- 4px 基础间距和 8/12px 圆角层级。
- 珊瑚稀缺使用、暖色表面、无装饰阴影/渐变。
- Do/Don't 和紧凑卡片的响应式规则。

## 6. 验证策略

- 新增源码级 JS 测试，确认 `board-page.js` 不再引用页头控件，且空状态保留添加入口。
- 新增设计系统测试，检查浅/深色关键令牌、字体栈和圆角。
- 运行 8 张默认卡片和基础模板的严格校验。
- 运行全部 JS 测试、可用的 Python 测试、`pnpm build` 和 `pnpm check`。
