import { TaskDetail as TaskDetailType } from '@/lib/api'
import { StatusBadge } from './StatusBadge'
import { TypeBadge } from './TypeBadge'
import { PayoutBadge } from './PayoutBadge'
import { SubmissionTable } from './SubmissionTable'
import { formatDeadline, formatBounty } from '@/lib/utils'

const BASE_SEPOLIA_EXPLORER = 'https://sepolia.basescan.org/tx'

function TxLink({ hash }: { hash: string }) {
  const short = `${hash.slice(0, 10)}…${hash.slice(-6)}`
  return (
    <a
      href={`${BASE_SEPOLIA_EXPLORER}/${hash}`}
      target="_blank"
      rel="noopener noreferrer"
      className="font-mono text-blue-400 hover:underline break-all"
      title={hash}
    >
      {short}
    </a>
  )
}

interface Props {
  task: TaskDetailType
}

export function TaskDetail({ task }: Props) {
  const { label, expired } = formatDeadline(task.deadline)

  return (
    <div className="flex flex-col gap-4 p-6 overflow-auto h-full">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-xl font-semibold">{task.title}</h2>
        <div className="flex gap-2 shrink-0">
          <TypeBadge type={task.type} />
          <StatusBadge status={task.status} />
        </div>
      </div>

      <p className="text-muted-foreground text-sm leading-relaxed">{task.description}</p>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {task.threshold !== null && (
          <div>
            <span className="text-muted-foreground">Threshold: </span>
            {task.threshold}
          </div>
        )}
        {task.max_revisions !== null && (
          <div>
            <span className="text-muted-foreground">Max Revisions: </span>
            {task.max_revisions}
          </div>
        )}
        <div>
          <span className="text-muted-foreground">Deadline: </span>
          <span className={expired ? 'text-red-400' : ''}>{label}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Winner: </span>
          {task.winner_submission_id
            ? `🏆 ${task.winner_submission_id.slice(0, 8)}…`
            : '—'}
        </div>
      </div>

      {task.bounty !== null && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <span className="text-muted-foreground">Bounty: </span>
            <span className="font-mono">{formatBounty(task.bounty)}</span>
          </div>
          {task.publisher_id && (
            <div>
              <span className="text-muted-foreground">Publisher: </span>
              <span className="font-mono">{task.publisher_id.slice(0, 8)}…</span>
            </div>
          )}
          {task.payment_tx_hash && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Payment Tx: </span>
              <TxLink hash={task.payment_tx_hash} />
            </div>
          )}
        </div>
      )}

      {task.payout_status && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Payout: </span>
            <PayoutBadge status={task.payout_status} />
          </div>
          {task.payout_amount !== null && (
            <div>
              <span className="text-muted-foreground">Payout Amount: </span>
              <span className="font-mono">{formatBounty(task.payout_amount)}</span>
            </div>
          )}
          {task.payout_tx_hash && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Payout Tx: </span>
              <TxLink hash={task.payout_tx_hash} />
            </div>
          )}
        </div>
      )}

      <div>
        <h3 className="text-sm font-medium mb-3">
          Submissions ({task.submissions.length})
        </h3>
        <SubmissionTable submissions={task.submissions} task={task} />
      </div>
    </div>
  )
}
