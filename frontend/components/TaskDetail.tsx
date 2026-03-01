'use client'

import { useState, useEffect } from 'react'
import { TaskDetail as TaskDetailType } from '@/lib/api'
import { StatusBadge } from './StatusBadge'
import { TypeBadge } from './TypeBadge'
import { PayoutBadge } from './PayoutBadge'
import { SubmissionTable } from './SubmissionTable'
import { ChallengePanel } from './ChallengePanel'
import { ComparativePanel } from './ComparativeTab'
import { SettlementPanel } from './SettlementPanel'
import { TaskStatusStepper } from './TaskStatusStepper'
import { formatDeadline, formatBounty } from '@/lib/utils'

const BASE_SEPOLIA_EXPLORER = 'https://sepolia.basescan.org/tx'

function formatHMS(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

type Tab = 'overview' | 'submissions' | 'comparative' | 'challenges' | 'settlement'

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
      <span className="text-muted-foreground w-24 shrink-0 text-xs">{label}</span>
      <span className="min-w-0 flex-1 break-all">{children}</span>
    </div>
  )
}

interface TabButtonProps {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}

function TabButton({ active, onClick, children }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
        active
          ? 'bg-accent text-foreground'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

interface Props {
  task: TaskDetailType
}

const CHALLENGE_STATUSES = new Set(['challenge_window', 'arbitrating', 'closed', 'voided'])

export function TaskDetail({ task }: Props) {
  const { label, expired } = formatDeadline(task.deadline)
  const showComparativeTab = task.type === 'quality_first'
  const showChallengesTab = task.type === 'quality_first' && CHALLENGE_STATUSES.has(task.status)
  const showSettlementTab = task.status === 'closed' || task.status === 'voided'
  const [tab, setTab] = useState<Tab>('overview')
  const [challengeRemain, setChallengeRemain] = useState<number | null>(null)

  useEffect(() => {
    if (task.status !== 'challenge_window' || !task.challenge_window_end) return
    const calc = () => Math.floor((new Date(task.challenge_window_end!).getTime() - Date.now()) / 1000)
    setChallengeRemain(calc())
    const timer = setInterval(() => setChallengeRemain(calc()), 1000)
    return () => clearInterval(timer)
  }, [task.status, task.challenge_window_end])

  function handleTabHint(hint: 'submissions' | 'challenges' | null) {
    if (hint === 'submissions') setTab('submissions')
    else if (hint === 'challenges' && showChallengesTab) setTab('challenges')
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Fixed header */}
      <div className="px-6 pt-6 pb-3 border-b border-border shrink-0">
        {/* Title row */}
        <div className="flex items-start justify-between gap-4 mb-1">
          <h2 className="text-lg font-semibold leading-snug">{task.title}</h2>
          <div className="flex gap-2 shrink-0">
            <TypeBadge type={task.type} />
            <StatusBadge status={task.status} />
          </div>
        </div>

        {/* Status stepper — pill-based, clickable */}
        <TaskStatusStepper
          type={task.type}
          status={task.status}
          onTabHint={handleTabHint}
        />

        {/* Tab bar */}
        <div className="flex gap-1 mt-3">
          <TabButton active={tab === 'overview'} onClick={() => setTab('overview')}>
            Overview
          </TabButton>
          <TabButton active={tab === 'submissions'} onClick={() => setTab('submissions')}>
            Submissions
            {task.submissions.length > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] bg-muted text-muted-foreground">
                {task.submissions.length}
              </span>
            )}
          </TabButton>
          {showComparativeTab && (
            <TabButton active={tab === 'comparative'} onClick={() => setTab('comparative')}>
              Comparative
            </TabButton>
          )}
          {showChallengesTab && (
            <TabButton active={tab === 'challenges'} onClick={() => setTab('challenges')}>
              Challenges
            </TabButton>
          )}
          {showSettlementTab && (
            <TabButton active={tab === 'settlement'} onClick={() => setTab('settlement')}>
              Settlement
            </TabButton>
          )}
        </div>
      </div>

      {/* Scrollable tab content */}
      <div className="flex-1 overflow-auto px-6 py-5">

        {/* ── Overview tab ── */}
        {tab === 'overview' && (
          <div className="flex flex-col gap-6">
            <p className="text-muted-foreground text-sm leading-relaxed">{task.description}</p>

            {/* Details + Payment side by side */}
            <div className="grid grid-cols-2 gap-6 items-start">
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
                      {challengeRemain !== null ? (
                        <span className={`font-mono ${challengeRemain <= 0 ? 'text-red-400' : ''}`}>
                          {challengeRemain <= 0 ? 'expired' : formatHMS(challengeRemain)}
                        </span>
                      ) : (
                        <span className="font-mono">{formatHMS(task.challenge_duration)}</span>
                      )}
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
            </div>

            {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
              <Section title="Acceptance Criteria">
                <ul className="space-y-1.5">
                  {task.acceptance_criteria.map((c, i) => (
                    <li key={i} className="flex gap-2 text-sm">
                      <span className="text-emerald-600 shrink-0 mt-0.5 text-xs">✓</span>
                      <span className="text-foreground/80 leading-snug">{c}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {task.scoring_dimensions && task.scoring_dimensions.length > 0 && (
              <Section title="Scoring Dimensions">
                <div className="space-y-3">
                  {task.scoring_dimensions.map((dim, i) => (
                    <div key={dim.dim_id ?? i} className="text-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-blue-300">{dim.name}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-muted-foreground">
                          {dim.dim_type}
                        </span>
                      </div>
                      {dim.description && (
                        <p className="text-muted-foreground text-xs mt-0.5">{dim.description}</p>
                      )}
                      {dim.scoring_guidance && (
                        <p className="text-muted-foreground/70 text-xs mt-0.5 italic">
                          {dim.scoring_guidance}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>
        )}

        {/* ── Submissions tab ── */}
        {tab === 'submissions' && (
          <SubmissionTable submissions={task.submissions} task={task} />
        )}

        {/* ── Comparative tab ── */}
        {tab === 'comparative' && showComparativeTab && (
          <ComparativePanel submissions={task.submissions} taskStatus={task.status} />
        )}

        {/* ── Challenges tab ── */}
        {tab === 'challenges' && showChallengesTab && (
          <ChallengePanel task={task} />
        )}

        {/* ── Settlement tab ── */}
        {tab === 'settlement' && showSettlementTab && (
          <SettlementPanel task={task} />
        )}
      </div>
    </div>
  )
}
