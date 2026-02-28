'use client'

import { useState } from 'react'
import type { SettlementSource, SettlementDistribution } from '@/lib/api'

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

interface Props {
  sources: SettlementSource[]
  distributions: SettlementDistribution[]
  escrowTotal: number
}

const W = 600
const H = 280
const PAD_Y = 16
const NODE_W = 120
const POOL_W = 40
const USABLE_H = H - PAD_Y * 2
const MIN_NODE_H = 18

const LEFT_X = 0
const POOL_X = (W - POOL_W) / 2
const RIGHT_X = W - NODE_W

export function SettlementSankey({ sources, distributions, escrowTotal }: Props) {
  const [hover, setHover] = useState<{ side: 'left' | 'right'; idx: number } | null>(null)

  if (escrowTotal <= 0) return null

  // Calculate node heights proportional to amount (with minimum)
  function layoutNodes<T extends { amount: number }>(items: T[]): { y: number; h: number }[] {
    const total = items.reduce((s, i) => s + i.amount, 0)
    if (total === 0) return items.map(() => ({ y: PAD_Y, h: MIN_NODE_H }))

    const gap = Math.min(6, USABLE_H / (items.length * 4))
    const totalGap = gap * Math.max(0, items.length - 1)
    const availH = USABLE_H - totalGap

    const rawHeights = items.map((i) => (i.amount / total) * availH)
    const heights = rawHeights.map((h) => Math.max(h, MIN_NODE_H))
    const totalH = heights.reduce((s, h) => s + h, 0) + totalGap
    const startY = PAD_Y + Math.max(0, (USABLE_H + totalGap - totalH) / 2)

    const result: { y: number; h: number }[] = []
    let cy = startY
    for (const h of heights) {
      result.push({ y: cy, h })
      cy += h + gap
    }
    return result
  }

  const srcLayout = layoutNodes(sources)
  const dstLayout = layoutNodes(distributions)
  const poolY = PAD_Y
  const poolH = USABLE_H

  function bezier(
    x1: number, y1: number,
    x2: number, y2: number,
  ): string {
    const cx1 = x1 + (x2 - x1) * 0.45
    const cx2 = x2 - (x2 - x1) * 0.45
    return `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`
  }

  function formatAmount(n: number): string {
    return n < 0.01 ? n.toFixed(4) : n.toFixed(2)
  }

  const isActive = (side: 'left' | 'right', idx: number) =>
    hover !== null && hover.side === side && hover.idx === idx

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ maxHeight: 280 }}
    >
      {/* Left-to-pool flows */}
      {sources.map((src, i) => {
        const s = srcLayout[i]
        const midS = s.y + s.h / 2
        const poolBand = poolY + (poolH * (s.y - PAD_Y)) / USABLE_H
        const poolBandH = (poolH * s.h) / USABLE_H
        const midP = poolBand + poolBandH / 2
        const strokeW = Math.max(2, (src.amount / escrowTotal) * (USABLE_H * 0.6))
        const active = isActive('left', i)
        return (
          <path
            key={`lf-${i}`}
            d={bezier(LEFT_X + NODE_W, midS, POOL_X, midP)}
            fill="none"
            stroke={sourceColor(src)}
            strokeWidth={strokeW}
            opacity={hover === null || active ? 0.45 : 0.12}
            className="transition-opacity duration-150"
          />
        )
      })}

      {/* Pool-to-right flows */}
      {distributions.map((dst, i) => {
        const d = dstLayout[i]
        const midD = d.y + d.h / 2
        const poolBand = poolY + (poolH * (d.y - PAD_Y)) / USABLE_H
        const poolBandH = (poolH * d.h) / USABLE_H
        const midP = poolBand + poolBandH / 2
        const strokeW = Math.max(2, (dst.amount / escrowTotal) * (USABLE_H * 0.6))
        const active = isActive('right', i)
        return (
          <path
            key={`rf-${i}`}
            d={bezier(POOL_X + POOL_W, midP, RIGHT_X, midD)}
            fill="none"
            stroke={DIST_COLORS[dst.type] ?? '#a1a1aa'}
            strokeWidth={strokeW}
            opacity={hover === null || active ? 0.45 : 0.12}
            className="transition-opacity duration-150"
          />
        )
      })}

      {/* Pool node */}
      <rect
        x={POOL_X}
        y={poolY}
        width={POOL_W}
        height={poolH}
        rx={6}
        fill="#27272a"
        stroke="#52525b"
        strokeWidth={1}
      />
      <text
        x={POOL_X + POOL_W / 2}
        y={poolY + poolH / 2 - 8}
        textAnchor="middle"
        fill="#a1a1aa"
        fontSize={10}
        fontWeight={600}
      >
        Pool
      </text>
      <text
        x={POOL_X + POOL_W / 2}
        y={poolY + poolH / 2 + 8}
        textAnchor="middle"
        fill="#e4e4e7"
        fontSize={11}
        fontFamily="monospace"
      >
        {formatAmount(escrowTotal)}
      </text>

      {/* Source nodes (left) */}
      {sources.map((src, i) => {
        const s = srcLayout[i]
        const active = isActive('left', i)
        return (
          <g
            key={`sn-${i}`}
            onMouseEnter={() => setHover({ side: 'left', idx: i })}
            onMouseLeave={() => setHover(null)}
            className="cursor-pointer"
          >
            <rect
              x={LEFT_X}
              y={s.y}
              width={NODE_W}
              height={s.h}
              rx={4}
              fill={sourceColor(src)}
              opacity={hover === null || active ? 0.85 : 0.3}
              className="transition-opacity duration-150"
            />
            {s.h >= 28 && (
              <>
                <text
                  x={LEFT_X + 8}
                  y={s.y + s.h / 2 - 4}
                  fill="#18181b"
                  fontSize={10}
                  fontWeight={600}
                >
                  {src.label.length > 16 ? src.label.slice(0, 14) + '..' : src.label}
                </text>
                <text
                  x={LEFT_X + 8}
                  y={s.y + s.h / 2 + 10}
                  fill="#18181b"
                  fontSize={10}
                  fontFamily="monospace"
                >
                  {formatAmount(src.amount)}
                </text>
              </>
            )}
            {s.h < 28 && s.h >= MIN_NODE_H && (
              <text
                x={LEFT_X + 8}
                y={s.y + s.h / 2 + 3.5}
                fill="#18181b"
                fontSize={9}
                fontWeight={600}
              >
                {formatAmount(src.amount)}
              </text>
            )}
            {/* Tooltip on hover */}
            {active && (
              <title>{`${src.label}: ${formatAmount(src.amount)} USDC${src.verdict ? ` (${src.verdict})` : ''}`}</title>
            )}
          </g>
        )
      })}

      {/* Distribution nodes (right) */}
      {distributions.map((dst, i) => {
        const d = dstLayout[i]
        const color = DIST_COLORS[dst.type] ?? '#a1a1aa'
        const active = isActive('right', i)
        return (
          <g
            key={`dn-${i}`}
            onMouseEnter={() => setHover({ side: 'right', idx: i })}
            onMouseLeave={() => setHover(null)}
            className="cursor-pointer"
          >
            <rect
              x={RIGHT_X}
              y={d.y}
              width={NODE_W}
              height={d.h}
              rx={4}
              fill={color}
              opacity={hover === null || active ? 0.85 : 0.3}
              className="transition-opacity duration-150"
            />
            {d.h >= 28 && (
              <>
                <text
                  x={RIGHT_X + 8}
                  y={d.y + d.h / 2 - 4}
                  fill="#18181b"
                  fontSize={10}
                  fontWeight={600}
                >
                  {dst.label.length > 16 ? dst.label.slice(0, 14) + '..' : dst.label}
                </text>
                <text
                  x={RIGHT_X + 8}
                  y={d.y + d.h / 2 + 10}
                  fill="#18181b"
                  fontSize={10}
                  fontFamily="monospace"
                >
                  {formatAmount(dst.amount)}
                </text>
              </>
            )}
            {d.h < 28 && d.h >= MIN_NODE_H && (
              <text
                x={RIGHT_X + 8}
                y={d.y + d.h / 2 + 3.5}
                fill="#18181b"
                fontSize={9}
                fontWeight={600}
              >
                {formatAmount(dst.amount)}
              </text>
            )}
            {active && (
              <title>{`${dst.label}: ${formatAmount(dst.amount)} USDC`}</title>
            )}
          </g>
        )
      })}
    </svg>
  )
}
