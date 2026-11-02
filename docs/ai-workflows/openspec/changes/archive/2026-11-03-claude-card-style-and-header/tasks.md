# 任务清单：claude-card-style-and-header

状态：已完成（2026-11-03）。

## 1. 页头

- [x] 1.1 先补回归测试：看板源码不得注册 `WorkspacePageHeaderControl`，空看板必须有添加入口。
- [x] 1.2 移除 `Header` 和页头投射，在空状态增加内联添加按钮。
- [x] 1.3 确认命令面板仍可重新加载，并在非空看板的右下角浮动操作组保留添加卡片入口。

## 2. Claude 设计系统

- [x] 2.1 先补令牌回归测试，固定珊瑚、暖奶油、暖黑、字体栈和圆角。
- [x] 2.2 迁移 `runtime/card-tokens.css` 的浅色/深色令牌、字体层级和组件状态。
- [x] 2.3 审计 8 张默认卡片和基础模板，仅修正与新设计语言冲突的局部 CSS。
- [x] 2.4 重写 `card-author` 设计参考并更新技能描述。

## 3. 打包与验证

- [x] 3.1 重建 `desktop/plugin.js`。
- [x] 3.2 运行 JS 测试、相关 Python 测试、严格卡片/模板校验。（JS 91/91，Python 119/119）
- [x] 3.3 运行 `pnpm check`，审查 diff 与规格覆盖。
- [x] 3.4 执行 `workflow-close` 并归档本变更。
