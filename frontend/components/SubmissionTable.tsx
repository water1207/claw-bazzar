'use client'

import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Submission, Task, useUser } from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'
import { FeedbackCard } from '@/components/FeedbackCard'
import { scoreColor } from '@/lib/utils'

function WorkerCell({ workerId }: { workerId: string }) {
  const { data: user } = useUser(workerId)
  if (!user) {
    return <span className="font-mono text-xs text-muted-foreground">{workerId.slice(0, 8)}…</span>
  }
  return (
    <span className="flex items-center gap-1.5 flex-wrap">
      <span className="text-sm">{user.nickname}</span>
      <TrustBadge tier={user.trust_tier} score={user.trust_score} />
    </span>
  )
}

const STATUS_COLOR: Record<string, string> = {
  pending:         'text-muted-foreground',
  gate_passed:     'text-blue-400',
  gate_failed:     'text-red-400',
  policy_violation:'text-orange-400',
  scored:          'text-green-400',
}

interface Props {
  submissions: Submission[]
  task: Task
}

export function SubmissionTable({ submissions, task }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-32">Worker</TableHead>
          <TableHead className="w-8 text-center">Rev</TableHead>
          <TableHead className="w-16 text-center">Score</TableHead>
          <TableHead className="w-24">Status</TableHead>
          <TableHead>Oracle Feedback</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {submissions.map((sub) => {
          const isWinner = sub.id === task.winner_submission_id
          return (
            <TableRow
              key={sub.id}
              className={isWinner ? 'bg-yellow-500/10 border-yellow-500/30' : ''}
            >
              <TableCell>
                <WorkerCell workerId={sub.worker_id} />
              </TableCell>
              <TableCell className="text-center text-sm text-muted-foreground">
                {sub.revision}
              </TableCell>
              <TableCell className={`text-center font-mono text-sm ${scoreColor(sub.score, task.threshold)}`}>
                {sub.score !== null ? (sub.score * 100).toFixed(1) : '—'}
                {isWinner && ' 🏆'}
              </TableCell>
              <TableCell className={`text-xs ${STATUS_COLOR[sub.status] ?? 'text-muted-foreground'}`}>
                {sub.status.replace('_', ' ')}
              </TableCell>
              <TableCell className="py-2 max-w-sm">
                {sub.oracle_feedback
                  ? <FeedbackCard raw={sub.oracle_feedback} taskStatus={task.status} />
                  : <span className="text-muted-foreground text-xs">—</span>
                }
              </TableCell>
            </TableRow>
          )
        })}
        {submissions.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} className="text-center text-muted-foreground py-8 text-sm">
              No submissions yet
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
