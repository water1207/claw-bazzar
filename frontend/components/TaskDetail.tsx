import { TaskDetail as TaskDetailType } from '@/lib/api'
import { StatusBadge } from './StatusBadge'
import { TypeBadge } from './TypeBadge'
import { PayoutBadge } from './PayoutBadge'
import { SubmissionTable } from './SubmissionTable'
import { ChallengePanel } from './ChallengePanel'
import { TaskStatusStepper } from './TaskStatusStepper'
import { formatDeadline, formatBounty } from '@/lib/utils'

const BASE_SEPOLIA_EXPLORER = 'https://sepolia.basescan.org/tx'

function TxLink({ hash }: { hash: string }) {
  const short = `${hash.slice(0, 10)}…${hash.slice(-6)}`
  return (
    <a
      href={`${BASE_SEPOLIA_EXPLORER}/${hash}`}
      target="_blank"
      rel="noopener noreferrer"
      className="font-mono text-xs text-blue-400 hover:underline"
      title={hash}
    >
      {short}
    </a>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-2.5">
        {title}
      </h3>
      {children}
    </div>
  )
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 text-sm min-w-0">
      <span className="text-muted-foreground w-28 shrink-0 text-xs">{label}</span>
      <span className="min-w-0 flex-1 break-all">{children}</span>
    </div>
  )
}

interface Props {
  task: TaskDetailType
}

export function TaskDetail({ task }: Props) {
  const { label, expired } = formatDeadline(task.deadline)

  return (
    <div className="flex flex-col gap-6 p-6 overflow-auto h-full">
      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-4 mb-1">
          <h2 className="text-lg font-semibold leading-snug">{task.title}</h2>
          <div className="flex gap-2 shrink-0">
            <TypeBadge type={task.type} />
            <StatusBadge status={task.status} />
          </div>
        </div>
        <TaskStatusStepper type={task.type} status={task.status} />
      </div>

      {/* Description */}
      <p className="text-muted-foreground text-sm leading-relaxed">{task.description}</p>

      {/* Core details */}
      <Section title="Details">
        <div className="space-y-2">
          {task.bounty !== null && (
            <MetaRow label="Bounty">
              <span className="font-mono font-medium text-green-400">{formatBounty(task.bounty)}</span>
            </MetaRow>
          )}
          {task.publisher_id && (
            <MetaRow label="Publisher">
              <span className="flex items-center gap-2 flex-wrap">
                {task.publisher_nickname && (
                  <span className="text-white">{task.publisher_nickname}</span>
                )}
                <span
                  className="font-mono text-xs text-muted-foreground cursor-pointer hover:text-blue-400"
                  title={`${task.publisher_id}（点击复制）`}
                  onClick={() => navigator.clipboard.writeText(task.publisher_id!)}
                >
                  {task.publisher_id.slice(0, 8)}…
                </span>
              </span>
            </MetaRow>
          )}
          <MetaRow label="Deadline">
            <span className={expired ? 'text-red-400' : ''}>{label}</span>
          </MetaRow>
          {task.threshold !== null && (
            <MetaRow label="Threshold">
              <span>{task.threshold}</span>
            </MetaRow>
          )}
          {task.max_revisions !== null && (
            <MetaRow label="Max Revisions">
              <span>{task.max_revisions}</span>
            </MetaRow>
          )}
          {task.submission_deposit !== null && task.submission_deposit > 0 && (
            <MetaRow label="Submit Deposit">
              <span className="font-mono">{formatBounty(task.submission_deposit)}</span>
            </MetaRow>
          )}
          {task.challenge_duration !== null && (
            <MetaRow label="Challenge Window">
              <span>{task.challenge_duration}h</span>
            </MetaRow>
          )}
          {task.winner_submission_id && (
            <MetaRow label="Winner">
              <span className="font-mono text-yellow-400">
                🏆 {task.winner_submission_id.slice(0, 8)}…
              </span>
            </MetaRow>
          )}
        </div>
      </Section>

      {/* Acceptance Criteria */}
      {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
        <Section title="Acceptance Criteria">
          <ul className="space-y-1.5">
            {task.acceptance_criteria.map((c, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="text-muted-foreground shrink-0 mt-0.5 text-xs">✓</span>
                <span className="text-foreground/80 leading-snug">{c}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Scoring Dimensions */}
      {task.scoring_dimensions && task.scoring_dimensions.length > 0 && (
        <Section title="Scoring Dimensions">
          <div className="space-y-2">
            {task.scoring_dimensions.map((dim, i) => (
              <div key={i} className="text-sm">
                <span className="font-medium text-blue-300">{dim.name}</span>
                {dim.description && (
                  <span className="text-muted-foreground ml-2 text-xs">{dim.description}</span>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Payment & Payout */}
      {(task.payment_tx_hash || task.escrow_tx_hash || task.payout_status) && (
        <Section title="Payment">
          <div className="space-y-2">
            {task.payment_tx_hash && (
              <MetaRow label="Payment Tx">
                <TxLink hash={task.payment_tx_hash} />
              </MetaRow>
            )}
            {task.escrow_tx_hash && (
              <MetaRow label="Escrow Tx">
                <TxLink hash={task.escrow_tx_hash} />
              </MetaRow>
            )}
            {task.payout_status && (
              <MetaRow label="Payout">
                <span className="flex items-center gap-2">
                  <PayoutBadge status={task.payout_status} />
                  {task.payout_amount !== null && (
                    <span className="font-mono text-xs">{formatBounty(task.payout_amount)}</span>
                  )}
                </span>
              </MetaRow>
            )}
            {task.payout_tx_hash && (
              <MetaRow label="Payout Tx">
                <TxLink hash={task.payout_tx_hash} />
              </MetaRow>
            )}
          </div>
        </Section>
      )}

      {/* Submissions */}
      <Section title={`Submissions (${task.submissions.length})`}>
        <SubmissionTable submissions={task.submissions} task={task} />
      </Section>

      <ChallengePanel task={task} />
    </div>
  )
}
