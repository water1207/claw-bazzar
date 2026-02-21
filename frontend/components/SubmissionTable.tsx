import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Submission, Task } from '@/lib/api'
import { scoreColor } from '@/lib/utils'

interface Props {
  submissions: Submission[]
  task: Task
}

export function SubmissionTable({ submissions, task }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Worker</TableHead>
          <TableHead>Rev</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Feedback</TableHead>
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
              <TableCell className="font-mono text-sm">{sub.worker_id}</TableCell>
              <TableCell>{sub.revision}</TableCell>
              <TableCell className={scoreColor(sub.score, task.threshold)}>
                {sub.score !== null ? sub.score.toFixed(2) : '—'}
                {isWinner && ' 🏆'}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">{sub.status}</TableCell>
              <TableCell className="text-muted-foreground text-sm max-w-xs truncate">
                {sub.oracle_feedback ?? '—'}
              </TableCell>
            </TableRow>
          )
        })}
        {submissions.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} className="text-center text-muted-foreground py-6">
              No submissions yet
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
