'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  useChallenges, createChallenge,
  useArbiterVotes, submitArbiterVote,
} from '@/lib/api'
import type {
  TaskDetail, Challenge, ChallengeVerdict,
} from '@/lib/api'

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

function ArbiterVotingPanel({ challengeId }: { challengeId: string }) {
  const { data: votes = [] } = useArbiterVotes(challengeId)

  if (votes.length === 0) return null

  const voted = votes.filter((v) => v.vote !== null).length
  const total = votes.length

  return (
    <div className="mt-2 p-3 bg-zinc-800 border border-zinc-600 rounded space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">Jury Votes</span>
        <span className="text-xs text-muted-foreground">{voted}/{total} voted</span>
      </div>
      <div className="space-y-1">
        {votes.map((v) => (
          <div key={v.id} className="flex items-center justify-between text-xs">
            <span className="font-mono text-muted-foreground">
              {v.arbiter_user_id.slice(0, 8)}...
            </span>
            {v.vote ? (
              <div className="flex items-center gap-2">
                <VerdictBadge verdict={v.vote} />
                {v.feedback && (
                  <span className="text-muted-foreground max-w-xs truncate">{v.feedback}</span>
                )}
              </div>
            ) : (
              <span className="text-yellow-400">pending...</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function ArbiterVoteForm({ challenge, onVoted }: {
  challenge: Challenge
  onVoted: () => void
}) {
  const [verdict, setVerdict] = useState<ChallengeVerdict | ''>('')
  const [feedback, setFeedback] = useState('')
  const [arbiterUserId, setArbiterUserId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!verdict || !feedback || !arbiterUserId) return
    setError(null)
    setSubmitting(true)
    try {
      await submitArbiterVote(challenge.id, {
        arbiter_user_id: arbiterUserId,
        verdict,
        feedback,
      })
      onVoted()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 mt-2 p-3 bg-zinc-800 border border-zinc-600 rounded">
      <p className="text-xs font-medium">Submit Arbiter Vote</p>
      <Input
        value={arbiterUserId}
        onChange={(e) => setArbiterUserId(e.target.value)}
        placeholder="Your arbiter user ID"
        className="h-8 text-xs"
        required
      />
      <Select value={verdict} onValueChange={(v) => setVerdict(v as ChallengeVerdict)}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder="Select verdict" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="upheld">Upheld</SelectItem>
          <SelectItem value="rejected">Rejected</SelectItem>
          <SelectItem value="malicious">Malicious</SelectItem>
        </SelectContent>
      </Select>
      <Textarea
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder="Verdict reasoning (required)"
        rows={2}
        className="text-xs"
        required
      />
      <Button type="submit" size="sm" disabled={submitting || !verdict || !feedback || !arbiterUserId}>
        {submitting ? 'Submitting...' : 'Submit Vote'}
      </Button>
      {error && <p className="text-xs text-red-400 break-all">{error}</p>}
    </form>
  )
}

function ChallengeCreateForm({ task, onCreated }: {
  task: TaskDetail
  onCreated: () => void
}) {
  const [subId, setSubId] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const nonWinnerSubs = task.submissions.filter(
    (s) => s.id !== task.winner_submission_id && s.status === 'scored'
  )

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await createChallenge(task.id, {
        challenger_submission_id: subId,
        reason,
      })
      setSubId('')
      setReason('')
      onCreated()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 p-4 bg-zinc-900 border border-zinc-700 rounded">
      <p className="text-sm font-medium">Submit Challenge</p>
      <Select value={subId} onValueChange={setSubId}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder="Select your submission" />
        </SelectTrigger>
        <SelectContent>
          {nonWinnerSubs.map((s) => (
            <SelectItem key={s.id} value={s.id}>
              {s.worker_id.slice(0, 8)}... (score: {s.score?.toFixed(2) ?? '—'})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason for challenging the winner..."
        rows={3}
        required
      />
      <Button type="submit" size="sm" disabled={submitting || !subId}>
        {submitting ? 'Submitting...' : 'Submit Challenge'}
      </Button>
      {error && <p className="text-xs text-red-400 break-all">{error}</p>}
    </form>
  )
}

function ChallengeCard({ challenge, task, onJudged }: {
  challenge: Challenge
  task: TaskDetail
  onJudged: () => void
}) {
  const challengerSub = task.submissions.find(
    (s) => s.id === challenge.challenger_submission_id
  )
  const targetSub = task.submissions.find(
    (s) => s.id === challenge.target_submission_id
  )

  return (
    <div className="p-4 bg-zinc-900 border border-zinc-700 rounded space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <VerdictBadge verdict={challenge.verdict} />
          <span className="text-xs text-muted-foreground font-mono">
            {challenge.id.slice(0, 8)}...
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <div>
          <span className="text-muted-foreground">Challenger: </span>
          <span className="font-mono">
            {challengerSub ? `${challengerSub.worker_id.slice(0, 8)}... (${challengerSub.score?.toFixed(2) ?? '—'})` : challenge.challenger_submission_id.slice(0, 8) + '...'}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Target: </span>
          <span className="font-mono">
            {targetSub ? `${targetSub.worker_id.slice(0, 8)}... (${targetSub.score?.toFixed(2) ?? '—'})` : challenge.target_submission_id.slice(0, 8) + '...'}
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

      {task.status === 'arbitrating' && (
        <ArbiterVotingPanel challengeId={challenge.id} />
      )}

      {challenge.status === 'pending' && task.status === 'arbitrating' && (
        <ArbiterVoteForm challenge={challenge} onVoted={onJudged} />
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
  const { data: challenges = [], mutate } = useChallenges(task.id)

  const showCreateForm = task.status === 'challenge_window'
  const showArbiterHeader = task.status === 'arbitrating'
  const pendingCount = challenges.filter((c) => c.status === 'pending').length

  const windowLabel = useWindowCountdown(
    task.challenge_window_end,
    task.status === 'challenge_window',
  )

  if (
    task.type !== 'quality_first' ||
    !['challenge_window', 'arbitrating', 'closed'].includes(task.status)
  ) {
    return null
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">
          Challenges ({challenges.length})
          {showArbiterHeader && pendingCount > 0 && (
            <span className="text-yellow-400 ml-2">
              {pendingCount} pending verdict{pendingCount > 1 ? 's' : ''}
            </span>
          )}
        </h3>
        {windowLabel && (
          <span className="text-xs text-yellow-400">{windowLabel}</span>
        )}
      </div>

      {challenges.length === 0 && !showCreateForm && (
        <p className="text-xs text-muted-foreground">No challenges were filed.</p>
      )}

      {challenges.map((c) => (
        <ChallengeCard
          key={c.id}
          challenge={c}
          task={task}
          onJudged={() => mutate()}
        />
      ))}

      {showCreateForm && (
        <ChallengeCreateForm task={task} onCreated={() => mutate()} />
      )}
    </div>
  )
}
