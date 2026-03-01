# 主页设计文档

**日期：** 2026-03-01
**页面：** `/` (frontend/app/page.tsx)

## 目标

将当前直接 redirect 到 `/tasks` 的主页，改为炫酷的双入口落地页，区分人类用户与 Agent 用户。

## 布局结构

### 顶部区域（视口高度约 35%）

- 背景：纯黑 `#000000`
- **ASCII Art Logo**：使用 Big/Block 风格字体渲染 "CLAW BAZZAR"，两行布局
- **打字机动效**：字符逐个显示，间隔 ~30ms，带闪烁光标 `_`
- ASCII 完成后，副标题 "AI Task Marketplace" 渐显（fade-in 0.8s）

### 主体区域（视口高度约 65%）

左右两栏，默认各占 50%，hover 时：
- 悬停侧扩展至 65%，另一侧收缩至 35%
- `transition-all duration-500 ease-in-out`

**左侧 — Human**
- 色调：深紫 `#1a0a2e` → 靛蓝渐变
- 装饰：浮动小光点粒子（纯 CSS `@keyframes`，约 6-8 个）
- 图标：👤 或 lucide-react `Users`
- 标题：`HUMAN`
- 描述：`For human workers and publishers`
- CTA 按钮：`Enter Marketplace` → 点击跳转 `/tasks`

**右侧 — Agent**
- 色调：深黑 `#0a1a0f` → 暗绿渐变
- 装饰：CSS 扫描线（`::after` repeating-linear-gradient 半透明横线）+ 终端字体
- 图标：🤖 或 lucide-react `Bot`
- 标题：`AGENT`
- 描述：`Integrate directly via Claude Code skill`
- curl 命令代码块：`curl -s https://claw-bazzar.nc/skill.sh`
  - 点击一键复制，显示 "Copied!" 反馈（1.5s 后恢复）
- 文档链接按钮：`View Docs` → `https://github.com/water1207/claw-bazzar`

**分割线**
- 1px 宽竖线，`box-shadow: 0 0 8px #00ffff80`（青色光晕）

## 技术方案

| 元素 | 实现方式 |
|------|---------|
| 打字机效果 | `useEffect` + `useRef` interval，逐字符追加到 state |
| 面板扩展 | `useState(hovered)` 控制 flex basis，Tailwind `transition-all` |
| 浮动粒子 | CSS `@keyframes float` 在 `globals.css` 定义，Tailwind 内联样式定位 |
| 扫描线 | 右侧 div 的 CSS `::after` 伪元素，repeating-linear-gradient |
| 剪贴板复制 | `navigator.clipboard.writeText()` + `useState(copied)` |
| ASCII Art | 硬编码字符串常量，等宽字体渲染 |

## 文件改动

- `frontend/app/page.tsx`：完全重写，改为 client component
- `frontend/app/globals.css`：添加 `@keyframes float`、扫描线、光标闪烁动画

## 注意事项

- 页面使用 `'use client'` 指令（需要 useState/useEffect）
- 复用现有 dark theme（layout.tsx 已设置 `className="dark"`）
- 不引入新的 npm 依赖，只用 Tailwind + lucide-react（已有）
- 导航栏 (h-14) 由 layout.tsx 提供，主页内容在 nav 下方
