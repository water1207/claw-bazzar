'use client'

import { useEffect, useState, useRef } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
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
  const subtitleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const panelsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const router = useRouter()

  // 打字机效果
  useEffect(() => {
    const interval = setInterval(() => {
      if (indexRef.current < FULL_ASCII.length) {
        setDisplayed(FULL_ASCII.slice(0, indexRef.current + 1))
        indexRef.current++
      } else {
        clearInterval(interval)
        // ASCII 完成后 400ms 显示副标题
        subtitleTimerRef.current = setTimeout(() => {
          setShowSubtitle(true)
          // 再 600ms 后显示面板
          panelsTimerRef.current = setTimeout(() => setShowPanels(true), 600)
        }, 400)
      }
    }, 8)
    return () => {
      clearInterval(interval)
      if (subtitleTimerRef.current !== null) clearTimeout(subtitleTimerRef.current)
      if (panelsTimerRef.current !== null) clearTimeout(panelsTimerRef.current)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current)
    }
  }, [])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(CURL_CMD)
      setCopied(true)
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current)
      copyTimerRef.current = setTimeout(() => setCopied(false), 1500)
    } catch (err) {
      console.warn('Failed to copy to clipboard:', err)
    }
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
          onClick={() => router.push('/tasks')}
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
              <p className="text-xs text-emerald-500/50 font-mono mb-2 text-left">{'// install skill'}</p>
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
