# Claude 卡片设计增量规格

## 运行时设计系统

系统 MUST 向每张卡片注入基于 Claude DESIGN.md 的令牌和公共组件，并 MUST 使用以下核心视觉语言：

- 浅色画布 `#faf9f5`，浅色内容面 `#efe9de`，主文字 `#141413`，正文 `#3d3d3a`，弱化文字 `#6c6a64`。
- 珊瑚主色 `#cc785c`，按下/激活色 `#a9583e`，焦点环使用珊瑚色的透明扩展。
- 深色主题使用暖黑 `#181715`、深色升高面 `#252320`、暖白 `#faf9f5`和珊瑚主色，MUST NOT 回退到冷蓝强调色。
- 标题/核心数字使用 `Tiempos Headline, Cormorant Garamond, EB Garamond, Georgia, serif` 回退栈，正文使用 `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif`。
- 按钮和输入框使用 8px 圆角，内容块使用 12px 圆角，胶囊标签可使用全圆角。
- 层次依靠暖色表面和发丝线；默认 MUST NOT 使用装饰性阴影、渐变或冷蓝色。

### 场景：浅色卡片

- **WHEN** 宿主主题为浅色。
- **THEN** 卡片 MUST 使用暖奶油表面和暖黑文字。
- **AND** 主操作、链接和图表主系列 MUST 使用珊瑚强调色。

### 场景：深色卡片

- **WHEN** 宿主主题为深色。
- **THEN** 卡片 MUST 使用暖黑表面和暖白文字。
- **AND** 交互强调色 MUST 仍为珊瑚色。

## 默认卡片

8 张内置卡片 MUST 通过公共令牌和组件获得 Claude 风格。卡片自身的局部 CSS MUST NOT 重新引入 Apple 蓝、纯白画布、冷灰表面、装饰性阴影或渐变。

### 场景：默认卡片校验

- **WHEN** 对 8 张默认卡片执行严格包校验。
- **THEN** 每张卡片 MUST 无错误且无设计警告。
- **AND** 现有数据、交互、尺寸和深浅主题行为 MUST 保持。

## Agent 生成规范

`card-author` 技能、设计参考和基础模板 MUST 把 Claude DESIGN.md 作为默认卡片风格。文档 MUST 覆盖核心令牌、字体层级、圆角、间距、组件和 Do/Don't，并 MUST 指示 Agent 从基础模板开始。

### 场景：新卡片生成

- **WHEN** Agent 按 `card-author` 技能创建卡片。
- **THEN** 它 MUST 优先使用 `--hb-*` 令牌和 `hb-*` 组件类。
- **AND** 它 MUST NOT 自定义外部字体、写死品牌色、使用冷蓝主色或装饰性阴影/渐变。
