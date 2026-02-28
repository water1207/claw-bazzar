'use client'

import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { useChallenges, useJuryBallots } from '@/lib/api'
import type { TaskDetail, Challenge, ChallengeVerdict } from '@/lib/api'

function VerdictBadge({ verdict }: { verdict: ChallengeVerdict | null }) {
  if (!verdict) return <Badge variant="secondary">pending</Badge>
  const cfg: Record<ChallengeVerdict, { variant: 'default' | 'destructive' | 'outline'; label: string }> = {
    upheld:    { variant: 'default',     label: 'upheld' },
    rejected:  { variant: 'outline',     label: 'rejected' },
    malicious: { variant: 'destructive', label: 'malicious' },
  }
  const c = cfg[verdict]
  return <Badge variant={c.variant}>{c.label}</Badge>
}

function MergedVotingProgress({ taskId }: { taskId: string }) {
  const { data: ballots = [] } = useJuryBallots(taskId)

  if (ballots.length === 0) return null

  const voted = ballots.filter((b) => b.voted_at !== null).length
  const total = ballots.length
  const allVoted = total > 0 && voted === total

  // Count winner picks and malicious tags
  const winnerCounts: Record<string, number> = {}
  const maliciousCounts: Record<string, number> = {}

  if (allVoted) {
    for (const b of ballots) {
      if (b.winner_submission_id) {
        winnerCounts[b.winner_submission_id] = (winnerCounts[b.winner_submission_id] || 0) + 1
      }
      if (b.malicious_tags) {
        for (const tag of b.malicious_tags) {
          maliciousCounts[tag] = (maliciousCounts[tag] || 0) + 1
        }
      }
    }
  }

  return (
    <div className="mt-2 p-3 bg-zinc-800 border border-zinc-600 rounded space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">Merged Jury Votes</span>
        <span className="text-xs text-muted-foreground">{voted}/{total} voted</span>
      </div>

      {allVoted && (
        <div className="space-y-2">
          {/* Winner picks */}
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Winner picks:</span>
            {Object.entries(winnerCounts).map(([subId, count]) => (
              <div key={subId} className="flex items-center justify-between text-xs">
                <span className="font-mono text-muted-foreground">
                  {subId.slice(0, 8)}...
                </span>
                <Badge variant="default">{count} vote{count > 1 ? 's' : ''}</Badge>
              </div>
            ))}
          </div>

          {/* Malicious tags */}
          {Object.keys(maliciousCounts).length > 0 && (
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Malicious tags:</span>
              {Object.entries(maliciousCounts).map(([subId, count]) => (
                <div key={subId} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-muted-foreground">
                    {subId.slice(0, 8)}...
                  </span>
                  <Badge variant="destructive">{count} tag{count > 1 ? 's' : ''}</Badge>
                </div>
              ))}
            </div>
          )}

          {/* Individual ballot details */}
          <div className="space-y-1 border-t border-zinc-600 pt-2">
            {ballots.map((b) => (
              <div key={b.id} className="flex items-center justify-between text-xs">
                <span className="font-mono text-muted-foreground">
                  {b.arbiter_user_id.slice(0, 8)}...
                </span>
                <div className="flex items-center gap-1.5">
                  {b.winner_submission_id && (
                    <span className="text-muted-foreground">
                      picked {b.winner_submission_id.slice(0, 8)}...
                    </span>
                  )}
                  {b.malicious_tags && b.malicious_tags.length > 0 && (
                    <Badge variant="destructive" className="text-[10px]">
                      {b.malicious_tags.length} malicious
                    </Badge>
                  )}
                  {b.feedback && (
                    <span className="text-muted-foreground max-w-xs truncate" title={b.feedback}>
                      {b.feedback}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ChallengeCard({ challenge, task }: {
  challenge: Challenge
  task: TaskDetail
}) {
  const challengerSub = task.submissions.find(
    (s) => s.id === challenge.challenger_submission_id
  )
  const targetSub = task.submissions.find(
    (s) => s.id === challenge.target_submission_id
  )

  // In voided tasks, a "rejected" challenge verdict means the challenger was justified
  const isJustifiedWhistleblower =
    task.status === 'voided' && challenge.verdict === 'rejected'

  return (
    <div className="p-4 bg-zinc-900 border border-zinc-700 rounded space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isJustifiedWhistleblower ? (
            <Badge variant="default">justified</Badge>
          ) : (
            <VerdictBadge verdict={challenge.verdict} />
          )}
          <span className="text-xs text-muted-foreground font-mono">
            {challenge.id.slice(0, 8)}...
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <div>
          <span className="text-muted-foreground">Challenger: </span>
          <span className="font-mono">
            {challengerSub ? `${challengerSub.worker_id.slice(0, 8)}... (${challengerSub.score?.toFixed(2) ?? '\u2014'})` : challenge.challenger_submission_id.slice(0, 8) + '...'}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Target: </span>
          <span className="font-mono">
            {targetSub ? `${targetSub.worker_id.slice(0, 8)}... (${targetSub.score?.toFixed(2) ?? '\u2014'})` : challenge.target_submission_id.slice(0, 8) + '...'}
          </span>
        </div>
      </div>

      <div className="text-xs">
        <span className="text-muted-foreground">Reason: </span>
        <span>{challenge.reason}</span>
      </div>

      {challenge.deposit_tx_hash && (
        <div className="text-xs">
          <span className="text-muted-foreground">Deposit Tx: </span>
          <a
            href={`https://sepolia.basescan.org/tx/${challenge.deposit_tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-blue-400 hover:underline break-all"
            title={challenge.deposit_tx_hash}
          >
            {challenge.deposit_tx_hash.slice(0, 10)}...{challenge.deposit_tx_hash.slice(-6)}
          </a>
        </div>
      )}

      {challenge.status === 'judged' && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs border-t border-zinc-700 pt-2 mt-2">
          {challenge.arbiter_score !== null && (
            <div>
              <span className="text-muted-foreground">Arbiter Score: </span>
              <span className="font-mono">{challenge.arbiter_score.toFixed(2)}</span>
            </div>
          )}
          {challenge.arbiter_feedback && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Feedback: </span>
              <span>{challenge.arbiter_feedback}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface Props {
  task: TaskDetail
}

function computeWindowLabel(end: string | null): string | null {
  if (!end) return null
  const remaining = new Date(end).getTime() - Date.now()
  if (remaining <= 0) return 'window closing...'
  const mins = Math.floor(remaining / 60_000)
  const hrs = Math.floor(mins / 60)
  return hrs > 0 ? `${hrs}h ${mins % 60}m remaining` : `${mins}m remaining`
}

function useWindowCountdown(end: string | null, active: boolean) {
  const [label, setLabel] = useState<string | null>(() =>
    active ? computeWindowLabel(end) : null
  )
  useEffect(() => {
    if (!active || !end) return
    const id = setInterval(() => setLabel(computeWindowLabel(end)), 30_000)
    return () => clearInterval(id)
  }, [end, active])
  return active ? label : null
}

export function ChallengePanel({ task }: Props) {
  const { data: challenges = [] } = useChallenges(task.id)

  const pendingCount = challenges.filter((c) => c.status === 'pending').length

  const windowLabel = useWindowCountdown(
    task.challenge_window_end ?? null,
    task.status === 'challenge_window',
  )

  if (
    task.type !== 'quality_first' ||
    !['challenge_window', 'arbitrating', 'closed', 'voided'].includes(task.status)
  ) {
    return null
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Voided status banner */}
      {task.status === 'voided' && (
        <Badge variant="destructive" className="w-fit">
          Task Voided — PW judged malicious
        </Badge>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">
          Challenges ({challenges.length})
          {task.status === 'arbitrating' && pendingCount > 0 && (
            <span className="text-yellow-400 ml-2">
              {pendingCount} pending verdict{pendingCount > 1 ? 's' : ''}
            </span>
          )}
        </h3>
        {windowLabel && (
          <span className="text-xs text-yellow-400">{windowLabel}</span>
        )}
      </div>

      {/* Merged voting progress (replaces per-challenge voting display) */}
      {(task.status === 'arbitrating' || task.status === 'closed' || task.status === 'voided') && (
        <MergedVotingProgress taskId={task.id} />
      )}

      {challenges.length === 0 && (
        <p className="text-xs text-muted-foreground">No challenges were filed.</p>
      )}

      {challenges.map((c) => (
        <ChallengeCard
          key={c.id}
          challenge={c}
          task={task}
        />
      ))}
    </div>
  )
}
