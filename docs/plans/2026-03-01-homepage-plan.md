# Homepage Dual-Entry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将主页改为带 ASCII Art 打字机动效 + 左右分割双入口的炫酷落地页。

**Architecture:** 单个 Client Component (`page.tsx`) 管理打字机状态和 hover 状态；CSS 动画（浮动粒子、扫描线、光标闪烁）定义在 `globals.css`；无新依赖。

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind v4, tw-animate-css, lucide-react

---

## Task 1: 添加 CSS 动画到 globals.css

**Files:**
- Modify: `frontend/app/globals.css`

**Step 1: 在 globals.css 末尾追加动画定义**

在文件末尾（`@layer base { ... }` 之后）添加：

```css
/* 光标闪烁 */
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.cursor-blink {
  animation: blink 1s step-end infinite;
}

/* 粒子浮动 */
@keyframes float-up {
  0%   { transform: translateY(0) translateX(0); opacity: 0; }
  10%  { opacity: 0.6; }
  90%  { opacity: 0.3; }
  100% { transform: translateY(-120px) translateX(20px); opacity: 0; }
}

@keyframes float-up-2 {
  0%   { transform: translateY(0) translateX(0); opacity: 0; }
  10%  { opacity: 0.4; }
  90%  { opacity: 0.2; }
  100% { transform: translateY(-100px) translateX(-15px); opacity: 0; }
}

.particle {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #818cf8;
  pointer-events: none;
}

.particle:nth-child(1)  { left: 15%; bottom: 20%; animation: float-up 4s ease-in-out 0s infinite; }
.particle:nth-child(2)  { left: 30%; bottom: 35%; animation: float-up-2 5s ease-in-out 0.8s infinite; }
.particle:nth-child(3)  { left: 50%; bottom: 15%; animation: float-up 6s ease-in-out 1.2s infinite; }
.particle:nth-child(4)  { left: 65%; bottom: 40%; animation: float-up-2 4.5s ease-in-out 0.4s infinite; }
.particle:nth-child(5)  { left: 80%; bottom: 25%; animation: float-up 5.5s ease-in-out 2s infinite; }
.particle:nth-child(6)  { left: 10%; bottom: 60%; animation: float-up-2 4s ease-in-out 1.6s infinite; }
.particle:nth-child(7)  { left: 45%; bottom: 55%; animation: float-up 5s ease-in-out 0.2s infinite; background: #a78bfa; }
.particle:nth-child(8)  { left: 70%; bottom: 70%; animation: float-up-2 6s ease-in-out 1s infinite; background: #a78bfa; }

/* 扫描线覆盖层 */
.scanlines {
  position: relative;
}

.scanlines::after {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0, 255, 128, 0.03) 2px,
    rgba(0, 255, 128, 0.03) 4px
  );
  pointer-events: none;
  z-index: 1;
}

/* 分割线光晕 */
.divider-glow {
  width: 1px;
  background: linear-gradient(
    to bottom,
    transparent,
    rgba(0, 255, 255, 0.5) 20%,
    rgba(0, 255, 255, 0.8) 50%,
    rgba(0, 255, 255, 0.5) 80%,
    transparent
  );
  box-shadow: 0 0 8px rgba(0, 255, 255, 0.4), 0 0 16px rgba(0, 255, 255, 0.2);
  flex-shrink: 0;
}
```

**Step 2: 验证 CSS 文件无语法错误**

```bash
cd frontend && npm run lint
```
Expected: 无报错（ESLint 不检查 CSS，但确保没有破坏其他文件）

**Step 3: Commit**

```bash
cd frontend
git add app/globals.css
git commit -m "feat: add homepage CSS animations (particles, scanlines, cursor blink)"
```

---

## Task 2: 重写 page.tsx — 主页组件

**Files:**
- Modify: `frontend/app/page.tsx`（完全重写）

**Step 1: 准备 ASCII Art 常量**

ASCII art 使用以下字符串（两行，Big 风格）：

```
 ██████╗██╗      █████╗ ██╗    ██╗
██╔════╝██║     ██╔══██╗██║    ██║
██║     ██║     ███████║██║ █╗ ██║
██║     ██║     ██╔══██║██║███╗██║
╚██████╗███████╗██║  ██║╚███╔███╔╝
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝

██████╗  █████╗ ███████╗███████╗ █████╗ ██████╗
██╔══██╗██╔══██╗╚══███╔╝╚══███╔╝██╔══██╗██╔══██╗
██████╔╝███████║  ███╔╝   ███╔╝ ███████║██████╔╝
██╔══██╗██╔══██║ ███╔╝   ███╔╝  ██╔══██║██╔══██╗
██████╔╝██║  ██║███████╗███████╗██║  ██║██║  ██║
╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
```

**Step 2: 编写完整 page.tsx**

完全替换 `frontend/app/page.tsx` 内容：

```tsx
'use client'

import { useEffect, useState, useRef } from 'react'
import Link from 'next/link'
import { Users, Bot, ExternalLink, Copy, Check } from 'lucide-react'

const ASCII_LINE_1 = ` ██████╗██╗      █████╗ ██╗    ██╗
██╔════╝██║     ██╔══██╗██║    ██║
██║     ██║     ███████║██║ █╗ ██║
██║     ██║     ██╔══██║██║███╗██║
╚██████╗███████╗██║  ██║╚███╔███╔╝
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝`

const ASCII_LINE_2 = `██████╗  █████╗ ███████╗███████╗ █████╗ ██████╗
██╔══██╗██╔══██╗╚══███╔╝╚══███╔╝██╔══██╗██╔══██╗
██████╔╝███████║  ███╔╝   ███╔╝ ███████║██████╔╝
██╔══██╗██╔══██║ ███╔╝   ███╔╝  ██╔══██║██╔══██╗
██████╔╝██║  ██║███████╗███████╗██║  ██║██║  ██║
╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝`

const FULL_ASCII = ASCII_LINE_1 + '\n\n' + ASCII_LINE_2
const CURL_CMD = 'curl -s https://claw-bazzar.nc/skill.sh'

export default function Home() {
  const [displayed, setDisplayed] = useState('')
  const [showSubtitle, setShowSubtitle] = useState(false)
  const [showPanels, setShowPanels] = useState(false)
  const [hovered, setHovered] = useState<'human' | 'agent' | null>(null)
  const [copied, setCopied] = useState(false)
  const indexRef = useRef(0)

  // 打字机效果
  useEffect(() => {
    const interval = setInterval(() => {
      if (indexRef.current < FULL_ASCII.length) {
        setDisplayed(FULL_ASCII.slice(0, indexRef.current + 1))
        indexRef.current++
      } else {
        clearInterval(interval)
        // ASCII 完成后 400ms 显示副标题
        setTimeout(() => {
          setShowSubtitle(true)
          // 再 600ms 后显示面板
          setTimeout(() => setShowPanels(true), 600)
        }, 400)
      }
    }, 18)
    return () => clearInterval(interval)
  }, [])

  const handleCopy = async () => {
    await navigator.clipboard.writeText(CURL_CMD)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const humanWidth = hovered === 'human' ? 'flex-[65]' : hovered === 'agent' ? 'flex-[35]' : 'flex-[50]'
  const agentWidth = hovered === 'agent' ? 'flex-[65]' : hovered === 'human' ? 'flex-[35]' : 'flex-[50]'

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 3.5rem)' }}>
      {/* 顶部 ASCII Art 区域 */}
      <div className="flex flex-col items-center justify-center bg-black py-8 px-4 shrink-0">
        <pre
          className="font-mono text-green-400 leading-tight select-none overflow-x-auto max-w-full"
          style={{ fontSize: 'clamp(4px, 1.1vw, 13px)' }}
        >
          {displayed}
          <span className="cursor-blink text-green-300">█</span>
        </pre>

        <p
          className={`mt-4 text-muted-foreground text-sm tracking-[0.3em] uppercase transition-all duration-700 ${
            showSubtitle ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
          }`}
        >
          AI Task Marketplace
        </p>
      </div>

      {/* 左右分割面板 */}
      <div
        className={`flex flex-1 min-h-0 transition-all duration-500 ${
          showPanels ? 'opacity-100' : 'opacity-0'
        }`}
      >
        {/* Human 面板 */}
        <div
          className={`relative overflow-hidden flex flex-col items-center justify-center gap-6 cursor-pointer transition-all duration-500 ease-in-out ${humanWidth}`}
          style={{
            background: 'linear-gradient(135deg, #0f0520 0%, #1a0a3e 40%, #0d1b4b 100%)',
          }}
          onMouseEnter={() => setHovered('human')}
          onMouseLeave={() => setHovered(null)}
          onClick={() => window.location.href = '/tasks'}
        >
          {/* 粒子 */}
          <div className="absolute inset-0 pointer-events-none">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="particle" />
            ))}
          </div>

          {/* 内容 */}
          <div className="relative z-10 flex flex-col items-center gap-4 text-center px-8">
            <div className="w-16 h-16 rounded-2xl flex items-center justify-center"
              style={{ background: 'rgba(129,140,248,0.15)', border: '1px solid rgba(129,140,248,0.3)' }}>
              <Users className="w-8 h-8 text-indigo-400" />
            </div>

            <div>
              <h2 className="text-2xl font-bold tracking-widest text-white mb-1">HUMAN</h2>
              <p className="text-sm text-indigo-300/70">For workers and publishers</p>
            </div>

            <Link
              href="/tasks"
              className="mt-2 px-6 py-2.5 rounded-lg text-sm font-semibold text-white transition-all duration-200 hover:scale-105"
              style={{
                background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                boxShadow: '0 0 20px rgba(99,102,241,0.4)',
              }}
              onClick={e => e.stopPropagation()}
            >
              Enter Marketplace →
            </Link>
          </div>

          {/* 边缘光晕 */}
          <div className="absolute inset-0 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 80%, rgba(99,102,241,0.08) 0%, transparent 70%)' }} />
        </div>

        {/* 分割线 */}
        <div className="divider-glow self-stretch" />

        {/* Agent 面板 */}
        <div
          className={`scanlines relative overflow-hidden flex flex-col items-center justify-center gap-6 cursor-default transition-all duration-500 ease-in-out ${agentWidth}`}
          style={{
            background: 'linear-gradient(135deg, #030d07 0%, #071a0e 40%, #0a2010 100%)',
          }}
          onMouseEnter={() => setHovered('agent')}
          onMouseLeave={() => setHovered(null)}
        >
          {/* 内容 */}
          <div className="relative z-10 flex flex-col items-center gap-4 text-center px-8 w-full max-w-md">
            <div className="w-16 h-16 rounded-2xl flex items-center justify-center"
              style={{ background: 'rgba(0,255,128,0.1)', border: '1px solid rgba(0,255,128,0.25)' }}>
              <Bot className="w-8 h-8 text-emerald-400" />
            </div>

            <div>
              <h2 className="text-2xl font-bold tracking-widest text-white mb-1">AGENT</h2>
              <p className="text-sm text-emerald-400/60 font-mono">Integrate via Claude Code skill</p>
            </div>

            {/* curl 命令 */}
            <div className="w-full">
              <p className="text-xs text-emerald-500/50 font-mono mb-2 text-left">// install skill</p>
              <div
                className="flex items-center gap-2 px-4 py-3 rounded-lg font-mono text-sm cursor-pointer group transition-all duration-200 hover:scale-[1.02]"
                style={{
                  background: 'rgba(0,255,128,0.06)',
                  border: '1px solid rgba(0,255,128,0.2)',
                  boxShadow: '0 0 12px rgba(0,255,128,0.05)',
                }}
                onClick={handleCopy}
                title="Click to copy"
              >
                <span className="text-emerald-500/60 select-none">$</span>
                <span className="text-emerald-300 flex-1 text-left truncate">{CURL_CMD}</span>
                <button
                  className="shrink-0 transition-colors"
                  onClick={e => { e.stopPropagation(); handleCopy() }}
                >
                  {copied
                    ? <Check className="w-4 h-4 text-emerald-400" />
                    : <Copy className="w-4 h-4 text-emerald-600 group-hover:text-emerald-400" />
                  }
                </button>
              </div>
              {copied && (
                <p className="text-xs text-emerald-400 mt-1 font-mono text-center">Copied!</p>
              )}
            </div>

            {/* 文档链接 */}
            <a
              href="https://github.com/water1207/claw-bazzar"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-mono transition-all duration-200 hover:scale-105"
              style={{
                border: '1px solid rgba(0,255,128,0.25)',
                color: 'rgba(0,255,128,0.7)',
              }}
            >
              <ExternalLink className="w-4 h-4" />
              View Documentation
            </a>
          </div>

          {/* 边缘光晕 */}
          <div className="absolute inset-0 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 80%, rgba(0,255,128,0.05) 0%, transparent 70%)' }} />
        </div>
      </div>
    </div>
  )
}
```

**Step 3: 启动开发服务器验证**

```bash
cd frontend && npm run dev
```

打开 `http://localhost:3000` 验证：
- [ ] ASCII art 从第一个字符开始逐字打印
- [ ] 光标 `█` 在打印结束前持续闪烁
- [ ] 打印完成后 "AI Task Marketplace" 渐显
- [ ] 面板淡入，默认左右各 50%
- [ ] 悬停左侧 → 左侧扩展到 65%，过渡平滑
- [ ] 悬停右侧 → 右侧扩展到 65%，过渡平滑
- [ ] 点击 curl 命令块 → 剪贴板复制 + 显示 "Copied!"
- [ ] "View Documentation" 点击打开 GitHub 链接
- [ ] "Enter Marketplace →" 跳转到 `/tasks`
- [ ] 粒子在左侧面板浮动
- [ ] 右侧面板有扫描线叠加效果

**Step 4: Lint 检查**

```bash
cd frontend && npm run lint
```
Expected: 无报错

**Step 5: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/app/page.tsx
git commit -m "feat: homepage dual-entry with ASCII typewriter + split panels"
```

---

## Task 3: 收尾检查

**Step 1: 确认 layout.tsx 导航链接正常**

打开 `http://localhost:3000`，点击导航栏 "Claw Bazzar" logo，应回到主页（非直接跳 tasks）。

检查 `frontend/app/layout.tsx:20`：
```tsx
<Link href="/tasks" ...>  // ← 这行改为 href="/" 更合理
```

修改为：
```tsx
<Link href="/" className="font-bold text-base tracking-tight flex items-center gap-2">
```

**Step 2: Commit**

```bash
git add frontend/app/layout.tsx
git commit -m "fix: logo link points to homepage instead of /tasks"
```

---

## 验收标准

| 项目 | 验证方式 |
|------|---------|
| ASCII 打字机动效 | 目视确认逐字打印 + 光标闪烁 |
| 副标题渐显 | 打印完成后淡入 |
| 面板 hover 扩展 | 悬停时平滑 65/35 分配 |
| 粒子浮动 | 左侧面板可见浮动光点 |
| 扫描线 | 右侧面板可见细线纹理 |
| curl 复制 | 点击后剪贴板有内容 + Copied! 反馈 |
| 文档跳转 | 新标签打开 GitHub |
| Marketplace 跳转 | 导航到 /tasks |
| 响应式 | 1440px 和 1024px 下不错乱 |
