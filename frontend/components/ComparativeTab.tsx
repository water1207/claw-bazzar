'use client'

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

interface ComparativeTabProps {
  comparativeFeedback: string | null
  taskStatus: string
  allSubmissions: { id: string; worker_id: string; comparative_feedback: string | null }[]
}

function WorkerName({ workerId }: { workerId: string }) {
  const { data: user } = useUser(workerId)
  return <span>{user?.nickname ?? workerId.slice(0, 8) + '…'}</span>
}

export function ComparativeTab({ comparativeFeedback, taskStatus, allSubmissions }: ComparativeTabProps) {
  const isVisible = !['open', 'scoring'].includes(taskStatus)

  if (!isVisible) {
    return (
      <div className="text-muted-foreground text-[11px] py-2">
        评分中，待公开
      </div>
    )
  }

  // Find comparative_feedback from winner submission if current sub doesn't have it
  const feedbackSource = comparativeFeedback
    ?? allSubmissions.find(s => s.comparative_feedback)?.comparative_feedback

  if (!feedbackSource) {
    return (
      <div className="text-muted-foreground text-[11px] py-2">
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

  return (
    <div className="space-y-3 text-[11px]">
      <div>
        <p className="text-muted-foreground mb-1.5 font-medium">排名</p>
        <table className="w-full">
          <thead>
            <tr className="text-muted-foreground border-b border-zinc-800">
              <th className="text-left py-0.5 font-normal w-8">#</th>
              <th className="text-left py-0.5 font-normal">Worker</th>
              <th className="text-right py-0.5 font-normal w-14">分数</th>
            </tr>
          </thead>
          <tbody>
            {cf.rankings.map((r) => (
              <tr key={r.submission_id} className={`border-b border-zinc-800/50 ${r.rank === 1 ? 'text-yellow-400' : ''}`}>
                <td className="py-0.5 font-mono">{r.rank}</td>
                <td className="py-0.5"><WorkerName workerId={r.worker_id} /></td>
                <td className="py-0.5 text-right font-mono">{r.final_score.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <p className="text-muted-foreground mb-1 font-medium">横向比较分析</p>
        <div className="text-white whitespace-pre-wrap leading-relaxed">
          {cf.winner_rationale}
        </div>
      </div>
    </div>
  )
}
