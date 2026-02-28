'use client'
import { useState } from 'react'

interface GateCheckResult {
  criterion: string
  passed: boolean
  reason?: string
}

interface GateCheckFeedback {
  type: 'gate_check'
  overall_passed: boolean
  criteria_results?: GateCheckResult[]
  summary?: string
}

interface DimensionScore {
  band: string
  score: number
  evidence?: string
  feedback?: string
}

interface RevisionSuggestion {
  problem: string
  suggestion: string
  severity: 'high' | 'medium' | 'low'
}

interface IndividualScoringFeedback {
  type: 'individual_scoring'
  dimension_scores?: Record<string, DimensionScore>
  overall_band?: string
  revision_suggestions?: RevisionSuggestion[]
}

interface ScoringFeedback {
  type: 'scoring'
  gate_check?: { overall_passed: boolean; summary?: string }
  dimension_scores?: Record<string, DimensionScore>
  overall_band?: string
  revision_suggestions?: RevisionSuggestion[]
  passed?: boolean
}

type OracleFeedback = GateCheckFeedback | IndividualScoringFeedback | ScoringFeedback

const SEVERITY_COLOR: Record<string, string> = {
  high:   'text-red-400',
  medium: 'text-yellow-400',
  low:    'text-zinc-400',
}

const BAND_COLOR: Record<string, string> = {
  A: 'text-green-400',
  B: 'text-blue-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  E: 'text-red-400',
}

function BandBadge({ band }: { band: string }) {
  return (
    <span className={['font-mono font-bold', BAND_COLOR[band] ?? 'text-white'].join(' ')}>
      [{band}]
    </span>
  )
}

function DimTable({ dims }: { dims: Record<string, DimensionScore> }) {
  return (
    <table className="w-full text-[11px] mt-1">
      <thead>
        <tr className="text-muted-foreground border-b border-zinc-800">
          <th className="text-left py-0.5 font-normal">维度</th>
          <th className="text-center py-0.5 font-normal w-8">Band</th>
          <th className="text-right py-0.5 font-normal w-10">分数</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(dims).map(([id, d]) => (
          <tr key={id} className="border-b border-zinc-800/50" title={d.evidence}>
            <td className="py-0.5 text-muted-foreground pr-2">{id}</td>
            <td className="py-0.5 text-center"><BandBadge band={d.band} /></td>
            <td className="py-0.5 text-right font-mono text-white">{d.score}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Suggestions({ suggestions }: { suggestions: RevisionSuggestion[] }) {
  return (
    <div className="space-y-1.5">
      {suggestions.map((s, i) => (
        <div key={i} className="flex gap-1.5">
          <span className={['shrink-0 uppercase text-[9px] font-bold w-8 mt-0.5', SEVERITY_COLOR[s.severity] ?? ''].join(' ')}>
            {s.severity.slice(0, 3)}
          </span>
          <div>
            <p className="text-white leading-tight">{s.problem}</p>
            <p className="text-muted-foreground leading-tight">→ {s.suggestion}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

export function FeedbackCard({ raw }: { raw: string }) {
  const [showDims, setShowDims] = useState(false)

  let data: OracleFeedback
  try {
    data = JSON.parse(raw)
  } catch {
    return <p className="text-muted-foreground text-[11px] break-all">{raw}</p>
  }

  if (data.type === 'gate_check') {
    return (
      <div className="space-y-1 text-[11px]">
        <div className="flex items-center gap-2">
          <span className={data.overall_passed ? 'text-green-400 font-medium' : 'text-red-400 font-medium'}>
            Gate {data.overall_passed ? '✓ 通过' : '✗ 未通过'}
          </span>
        </div>
        {data.summary && <p className="text-muted-foreground">{data.summary}</p>}
        {!data.overall_passed && data.criteria_results && (
          <ul className="space-y-0.5 pl-2">
            {data.criteria_results.filter(c => !c.passed).map((c, i) => (
              <li key={i} className="text-red-300">
                ✗ {c.criterion}{c.reason ? `：${c.reason}` : ''}
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  if (data.type === 'individual_scoring') {
    return (
      <div className="space-y-2 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-medium">个人评分</span>
          {data.overall_band && <BandBadge band={data.overall_band} />}
        </div>
        {data.revision_suggestions && data.revision_suggestions.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1">修订建议：</p>
            <Suggestions suggestions={data.revision_suggestions} />
          </div>
        )}
        {data.dimension_scores && (
          <div>
            <button
              type="button"
              onClick={() => setShowDims(!showDims)}
              className="text-muted-foreground hover:text-white text-[11px]"
            >
              {showDims ? '▲ 隐藏维度详情' : '▼ 查看维度详情'}
            </button>
            {showDims && <DimTable dims={data.dimension_scores} />}
          </div>
        )}
      </div>
    )
  }

  if (data.type === 'scoring') {
    return (
      <div className="space-y-2 text-[11px]">
        <div className="flex items-center gap-2">
          {data.gate_check && (
            <span className={data.gate_check.overall_passed ? 'text-green-400' : 'text-red-400'}>
              Gate {data.gate_check.overall_passed ? '✓' : '✗'}
            </span>
          )}
          {data.overall_band && <BandBadge band={data.overall_band} />}
        </div>
        {data.revision_suggestions && data.revision_suggestions.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1">修订建议：</p>
            <Suggestions suggestions={data.revision_suggestions} />
          </div>
        )}
        {data.dimension_scores && (
          <div>
            <button
              type="button"
              onClick={() => setShowDims(!showDims)}
              className="text-muted-foreground hover:text-white text-[11px]"
            >
              {showDims ? '▲ 隐藏' : '▼ 维度详情'}
            </button>
            {showDims && <DimTable dims={data.dimension_scores} />}
          </div>
        )}
      </div>
    )
  }

  // Fallback: formatted JSON
  return (
    <pre className="text-[10px] text-muted-foreground overflow-auto max-h-32 whitespace-pre-wrap break-all">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
