'use client'

import { useState } from 'react'
import type { SettlementSource, SettlementDistribution } from '@/lib/api'

/* ── Colors ── */

const SOURCE_COLORS: Record<string, string> = {
  bounty: '#34d399',
  incentive: '#60a5fa',
  deposit: '#f87171',
}

function sourceColor(s: SettlementSource): string {
  if (s.type === 'deposit') {
    if (s.verdict === 'upheld') return '#34d399'
    if (s.verdict === 'malicious') return '#facc15'
    return '#f87171'
  }
  return SOURCE_COLORS[s.type] ?? '#a1a1aa'
}

const DIST_COLORS: Record<string, string> = {
  winner: '#34d399',
  refund: '#60a5fa',
  arbiter: '#a78bfa',
  platform: '#a1a1aa',
  publisher_refund: '#60a5fa',
}

function distColor(d: SettlementDistribution): string {
  return DIST_COLORS[d.type] ?? '#a1a1aa'
}

/* ── Layout constants ── */

const ROW_H = 36
const PAD_TOP = 12
const PAD_BOTTOM = 12
const LABEL_AREA_W = 180
const GAP = 60

function formatAmt(n: number): string {
  return n < 0.01 ? n.toFixed(4) : n.toFixed(2)
}

/* ── Component ── */

interface Props {
  sources: SettlementSource[]
  distributions: SettlementDistribution[]
  escrowTotal: number
}

export function SettlementSankey({ sources, distributions, escrowTotal }: Props) {
  const [hover, setHover] = useState<{ side: 'src' | 'dst'; idx: number } | null>(null)

  if (escrowTotal <= 0) return null

  const rows = Math.max(sources.length, distributions.length)
  const svgH = PAD_TOP + rows * ROW_H + PAD_BOTTOM
  const W = LABEL_AREA_W * 2 + GAP

  // Y center for each row
  const rowCenterY = (idx: number) => PAD_TOP + idx * ROW_H + ROW_H / 2

  // Stroke width scaling: min 1.5, max 20, proportional to escrow
  const maxStroke = Math.min(20, ROW_H * 0.5)
  const strokeW = (amount: number) => Math.max(1.5, (amount / escrowTotal) * maxStroke)

  // Build flow connections: each source flows through center to distributions
  // Simple model: all sources merge, then split to distributions
  const flows: { srcIdx: number; dstIdx: number; amount: number; color: string }[] = []

  // Proportional distribution: each source contributes to each distribution proportionally
  const totalSrc = sources.reduce((s, x) => s + x.amount, 0)
  if (totalSrc > 0) {
    for (let si = 0; si < sources.length; si++) {
      const srcShare = sources[si].amount / totalSrc
      for (let di = 0; di < distributions.length; di++) {
        const flowAmt = srcShare * distributions[di].amount
        if (flowAmt > 0) {
          flows.push({
            srcIdx: si,
            dstIdx: di,
            amount: flowAmt,
            color: distColor(distributions[di]),
          })
        }
      }
    }
  }

  // Bezier from left side to right side through center
  function flowPath(srcY: number, dstY: number): string {
    const x1 = LABEL_AREA_W
    const x2 = LABEL_AREA_W + GAP
    const cx1 = x1 + GAP * 0.4
    const cx2 = x2 - GAP * 0.4
    return `M ${x1},${srcY} C ${cx1},${srcY} ${cx2},${dstY} ${x2},${dstY}`
  }

  const isHoverSrc = (i: number) => hover?.side === 'src' && hover.idx === i
  const isHoverDst = (i: number) => hover?.side === 'dst' && hover.idx === i
  const flowActive = (si: number, di: number) => {
    if (!hover) return true
    return (hover.side === 'src' && hover.idx === si) ||
           (hover.side === 'dst' && hover.idx === di)
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${svgH}`}
      className="w-full"
      style={{ maxHeight: Math.max(svgH, 160) }}
    >
      {/* Flow curves */}
      {flows.map((f, i) => {
        const srcY = rowCenterY(f.srcIdx)
        const dstY = rowCenterY(f.dstIdx)
        const active = flowActive(f.srcIdx, f.dstIdx)
        return (
          <path
            key={`flow-${i}`}
            d={flowPath(srcY, dstY)}
            fill="none"
            stroke={f.color}
            strokeWidth={strokeW(f.amount)}
            opacity={active ? 0.35 : 0.08}
            className="transition-opacity duration-150"
          />
        )
      })}

      {/* Source rows (left) */}
      {sources.map((src, i) => {
        const cy = rowCenterY(i)
        const color = sourceColor(src)
        const active = isHoverSrc(i)
        const dimmed = hover !== null && !active
        return (
          <g
            key={`src-${i}`}
            onMouseEnter={() => setHover({ side: 'src', idx: i })}
            onMouseLeave={() => setHover(null)}
            className="cursor-pointer"
          >
            {/* Accent bar */}
            <rect
              x={0}
              y={cy - ROW_H / 2 + 4}
              width={4}
              height={ROW_H - 8}
              rx={2}
              fill={color}
              opacity={dimmed ? 0.3 : 1}
              className="transition-opacity duration-150"
            />
            {/* Label */}
            <text
              x={12}
              y={cy + 1}
              fill={dimmed ? '#52525b' : '#d4d4d8'}
              fontSize={11}
              fontWeight={500}
              dominantBaseline="middle"
              className="transition-all duration-150"
            >
              {src.label.length > 18 ? src.label.slice(0, 16) + '..' : src.label}
            </text>
            {/* Amount (right-aligned near center) */}
            <text
              x={LABEL_AREA_W - 6}
              y={cy + 1}
              fill={dimmed ? '#3f3f46' : '#a1a1aa'}
              fontSize={11}
              fontFamily="monospace"
              textAnchor="end"
              dominantBaseline="middle"
              className="transition-all duration-150"
            >
              {formatAmt(src.amount)}
            </text>
            {/* Hover tooltip */}
            {active && (
              <title>{`${src.label}: ${formatAmt(src.amount)} USDC${src.verdict ? ` (${src.verdict})` : ''}`}</title>
            )}
          </g>
        )
      })}

      {/* Distribution rows (right) */}
      {distributions.map((dst, i) => {
        const cy = rowCenterY(i)
        const color = distColor(dst)
        const active = isHoverDst(i)
        const dimmed = hover !== null && !active
        return (
          <g
            key={`dst-${i}`}
            onMouseEnter={() => setHover({ side: 'dst', idx: i })}
            onMouseLeave={() => setHover(null)}
            className="cursor-pointer"
          >
            {/* Accent bar */}
            <rect
              x={LABEL_AREA_W + GAP}
              y={cy - ROW_H / 2 + 4}
              width={4}
              height={ROW_H - 8}
              rx={2}
              fill={color}
              opacity={dimmed ? 0.3 : 1}
              className="transition-opacity duration-150"
            />
            {/* Label */}
            <text
              x={LABEL_AREA_W + GAP + 12}
              y={cy + 1}
              fill={dimmed ? '#52525b' : '#d4d4d8'}
              fontSize={11}
              fontWeight={500}
              dominantBaseline="middle"
              className="transition-all duration-150"
            >
              {dst.label.length > 18 ? dst.label.slice(0, 16) + '..' : dst.label}
            </text>
            {/* Amount (right edge) */}
            <text
              x={W - 4}
              y={cy + 1}
              fill={dimmed ? '#3f3f46' : '#a1a1aa'}
              fontSize={11}
              fontFamily="monospace"
              textAnchor="end"
              dominantBaseline="middle"
              className="transition-all duration-150"
            >
              {formatAmt(dst.amount)}
            </text>
            {/* Hover tooltip */}
            {active && (
              <title>{`${dst.label}: ${formatAmt(dst.amount)} USDC`}</title>
            )}
          </g>
        )
      })}
    </svg>
  )
}
