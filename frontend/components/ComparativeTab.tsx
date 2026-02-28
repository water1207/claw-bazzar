'use client'

import { useState } from 'react'
import { Submission } from '@/lib/api'
import { useUser } from '@/lib/api'

interface Ranking {
  rank: number
  submission_id: string
  worker_id: string
  final_score: number
}

interface ComparativeFeedback {
  winner_rationale: string
  rankings: Ranking[]
}

function WorkerName({ workerId }: { workerId: string }) {
  const { data: user } = useUser(workerId)
  return <span>{user?.nickname ?? workerId.slice(0, 8) + '…'}</span>
}

interface ComparativePanelProps {
  submissions: Submission[]
  taskStatus: string
}

export function ComparativePanel({ submissions, taskStatus }: ComparativePanelProps) {
  const [contentExpanded, setContentExpanded] = useState(false)
  const isVisible = !['open', 'scoring'].includes(taskStatus)

  if (!isVisible) {
    return (
      <div className="text-muted-foreground text-sm py-6 text-center">
        评分中，待公开
      </div>
    )
  }

  const feedbackSource = submissions.find(s => s.comparative_feedback)?.comparative_feedback

  if (!feedbackSource) {
    return (
      <div className="text-muted-foreground text-sm py-6 text-center">
        暂无横向比较数据
      </div>
    )
  }

  let cf: ComparativeFeedback
  try {
    cf = JSON.parse(feedbackSource)
  } catch {
    return null
  }

  const winnerRanking = cf.rankings.find(r => r.rank === 1)
  const winnerSubmission = winnerRanking
    ? submissions.find(s => s.id === winnerRanking.submission_id)
    : null

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-2.5">
          Rankings
        </h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b border-zinc-800">
              <th className="text-left py-1.5 font-normal w-10">#</th>
              <th className="text-left py-1.5 font-normal">Worker</th>
              <th className="text-right py-1.5 font-normal w-20">Score</th>
            </tr>
          </thead>
          <tbody>
            {cf.rankings.map((r) => (
              <tr key={r.submission_id} className={`border-b border-zinc-800/50 ${r.rank === 1 ? 'text-yellow-400' : ''}`}>
                <td className="py-1.5 font-mono">{r.rank}</td>
                <td className="py-1.5"><WorkerName workerId={r.worker_id} /></td>
                <td className="py-1.5 text-right font-mono">{r.final_score.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {winnerSubmission?.content && (
        <div>
          <button
            onClick={() => setContentExpanded(!contentExpanded)}
            className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-2.5 hover:text-foreground transition-colors"
          >
            <span className="text-xs">{contentExpanded ? '▼' : '▶'}</span>
            Winner Submission
          </button>
          {contentExpanded && (
            <div className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed bg-zinc-900/50 rounded-md p-3 border border-zinc-800 max-h-96 overflow-y-auto">
              {winnerSubmission.content}
            </div>
          )}
        </div>
      )}

      <div>
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-2.5">
          Winner Analysis
        </h3>
        <div className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
          {cf.winner_rationale}
        </div>
      </div>
    </div>
  )
}
