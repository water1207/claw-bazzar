'use client'

import { useState, useMemo, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  useTasks, useJuryBallots, submitJuryVote, registerUser, useUser,
  useChallenges,
} from '@/lib/api'
import type { TaskDetail, Challenge } from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'
import { getDevWalletAddress } from '@/lib/x402'
import { fetchUsdcBalance } from '@/lib/utils'
import { DEV_ARBITERS } from '@/lib/dev-wallets'

const EMPTY_TASKS: never[] = []

function ArbiterInfo({ userId }: { userId: string }) {
  const { data: user } = useUser(userId)
  if (!user) return <span className="text-xs text-muted-foreground">Loading...</span>
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium">{user.nickname}</span>
      <TrustBadge tier={user.trust_tier} score={user.trust_score} />
    </div>
  )
}

/** Build candidate pool: PW (winner) + all challenger submissions */
function buildCandidatePool(
  task: TaskDetail,
  challenges: Challenge[],
): { id: string; label: string; isPW: boolean }[] {
  const pool: { id: string; label: string; isPW: boolean }[] = []

  // PW = the current winner submission
  const subs = task.submissions ?? []
  const pwSub = subs.find((s) => s.id === task.winner_submission_id)
  if (pwSub) {
    pool.push({
      id: pwSub.id,
      label: `PW: ${pwSub.worker_id.slice(0, 8)}... (score: ${pwSub.score?.toFixed(2) ?? '\u2014'})`,
      isPW: true,
    })
  }

  // Challengers
  const challengerSubIds = new Set(challenges.map((c) => c.challenger_submission_id))
  for (const subId of challengerSubIds) {
    const sub = subs.find((s) => s.id === subId)
    if (sub) {
      pool.push({
        id: sub.id,
        label: `Challenger: ${sub.worker_id.slice(0, 8)}... (score: ${sub.score?.toFixed(2) ?? '\u2014'})`,
        isPW: false,
      })
    } else {
      pool.push({
        id: subId,
        label: `Challenger: ${subId.slice(0, 8)}...`,
        isPW: false,
      })
    }
  }
  return pool
}

export { buildCandidatePool }

interface MergedVoteCardProps {
  task: TaskDetail
  challenges: Challenge[]
  arbiterId: string
  onVoted: () => void
}

export function MergedVoteCard({ task, challenges, arbiterId, onVoted }: MergedVoteCardProps) {
  const { data: ballots = [], mutate } = useJuryBallots(task.id)
  const [winnerId, setWinnerId] = useState('')
  const [maliciousIds, setMaliciousIds] = useState<Set<string>>(new Set())
  const [feedback, setFeedback] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const candidates = useMemo(
    () => buildCandidatePool(task, challenges),
    [task, challenges],
  )

  const myBallot = ballots.find((b) => b.arbiter_user_id === arbiterId)
  const votedCount = ballots.filter((b) => b.voted_at !== null).length
  const totalCount = ballots.length
  const allVoted = totalCount > 0 && votedCount === totalCount
  const alreadyVoted = myBallot?.voted_at !== null && myBallot?.voted_at !== undefined

  // Mutual exclusion: selecting winner removes them from malicious
  const handleWinnerChange = useCallback((subId: string) => {
    setWinnerId(subId)
    setMaliciousIds((prev) => {
      if (prev.has(subId)) {
        const next = new Set(prev)
        next.delete(subId)
        return next
      }
      return prev
    })
  }, [])

  const handleMaliciousToggle = useCallback((subId: string) => {
    // Cannot tag winner as malicious
    if (subId === winnerId) return
    setMaliciousIds((prev) => {
      const next = new Set(prev)
      if (next.has(subId)) {
        next.delete(subId)
      } else {
        next.add(subId)
      }
      return next
    })
  }, [winnerId])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!winnerId || !feedback.trim()) return
    setError(null)
    setSubmitting(true)
    try {
      await submitJuryVote(task.id, {
        arbiter_user_id: arbiterId,
        winner_submission_id: winnerId,
        malicious_submission_ids: Array.from(maliciousIds),
        feedback: feedback.trim(),
      })
      setWinnerId('')
      setMaliciousIds(new Set())
      setFeedback('')
      mutate()
      onVoted()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-3 bg-zinc-900 border border-zinc-700 rounded space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground" title={task.id}>
          Task: {task.title}
        </span>
        <span className="text-xs text-muted-foreground">{votedCount}/{totalCount} voted</span>
      </div>

      {/* Ballot status list */}
      <div className="space-y-1">
        {ballots.map((b) => (
          <div key={b.id} className="flex items-center justify-between text-xs">
            <span className={`font-mono ${b.arbiter_user_id === arbiterId ? 'text-blue-400' : 'text-muted-foreground'}`}>
              {b.arbiter_user_id === arbiterId ? '(you)' : b.arbiter_user_id.slice(0, 8) + '...'}
            </span>
            {b.voted_at ? (
              <div className="flex items-center gap-1.5">
                <Badge variant="default">voted</Badge>
                {allVoted && b.winner_submission_id && (
                  <span className="text-muted-foreground">
                    winner: {b.winner_submission_id.slice(0, 8)}...
                  </span>
                )}
                {allVoted && b.malicious_tags && b.malicious_tags.length > 0 && (
                  <Badge variant="destructive">{b.malicious_tags.length} malicious</Badge>
                )}
              </div>
            ) : (
              <span className="text-yellow-400">pending...</span>
            )}
          </div>
        ))}
      </div>

      {/* Vote form */}
      {myBallot && !alreadyVoted && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 pt-2 border-t border-zinc-700">
          {/* Winner selection (radio group) */}
          <div>
            <Label className="text-xs mb-1.5 block">Pick Winner</Label>
            <div className="space-y-1.5" role="radiogroup" aria-label="Pick winner">
              {candidates.map((c) => (
                <label
                  key={c.id}
                  className="flex items-center gap-2 text-xs cursor-pointer hover:bg-zinc-800 p-1.5 rounded"
                >
                  <input
                    type="radio"
                    name={`winner-${task.id}`}
                    value={c.id}
                    checked={winnerId === c.id}
                    onChange={() => handleWinnerChange(c.id)}
                    className="accent-blue-500"
                  />
                  <span>{c.label}</span>
                  {c.isPW && <Badge variant="outline" className="text-[10px] px-1">PW</Badge>}
                </label>
              ))}
            </div>
          </div>

          {/* Malicious tags (checkbox group) */}
          <div>
            <Label className="text-xs mb-1.5 block">Tag Malicious (optional)</Label>
            <div className="space-y-1.5" role="group" aria-label="Tag malicious submissions">
              {candidates.map((c) => {
                const isWinner = winnerId === c.id
                return (
                  <label
                    key={c.id}
                    className={`flex items-center gap-2 text-xs p-1.5 rounded ${
                      isWinner ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer hover:bg-zinc-800'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={maliciousIds.has(c.id)}
                      disabled={isWinner}
                      onChange={() => handleMaliciousToggle(c.id)}
                      className="accent-red-500"
                    />
                    <span>{c.label}</span>
                  </label>
                )
              })}
            </div>
          </div>

          {/* Feedback */}
          <Textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Reasoning (required)"
            rows={2}
            className="text-xs"
            required
          />

          <Button type="submit" size="sm" disabled={submitting || !winnerId || !feedback.trim()}>
            {submitting ? 'Voting...' : 'Submit Merged Vote'}
          </Button>
          {error && <p className="text-xs text-red-400 break-all">{error}</p>}
        </form>
      )}

      {alreadyVoted && (
        <p className="text-xs text-green-400 pt-1 border-t border-zinc-700">
          You voted: winner = {myBallot?.winner_submission_id?.slice(0, 8)}...
        </p>
      )}

      {!myBallot && totalCount > 0 && (
        <p className="text-xs text-muted-foreground pt-1 border-t border-zinc-700">
          Not assigned to this task&#39;s jury
        </p>
      )}
    </div>
  )
}

function TaskVoteSection({ task, arbiterId, onVoted }: {
  task: TaskDetail
  arbiterId: string
  onVoted: () => void
}) {
  const { data: challenges = [] } = useChallenges(task.id)

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-1">
        Task: <span className="text-white">{task.title}</span>
      </p>
      <MergedVoteCard
        task={task}
        challenges={challenges}
        arbiterId={arbiterId}
        onVoted={onVoted}
      />
    </div>
  )
}

export function ArbiterPanel() {
  const [activeIdx, setActiveIdx] = useState(0)
  const [arbiterIds, setArbiterIds] = useState<string[]>(() => DEV_ARBITERS.map(() => ''))
  const [pollKey, setPollKey] = useState(0)
  const [balances, setBalances] = useState<string[]>(() => DEV_ARBITERS.map(() => '...'))
  const [balRefreshing, setBalRefreshing] = useState(false)

  const arbiterAddresses = useMemo(
    () => DEV_ARBITERS.map((a) => {
      try { return getDevWalletAddress(a.key) } catch { return null }
    }),
    [],
  )

  const { data: tasks = EMPTY_TASKS } = useTasks()
  const arbitratingTasks = useMemo(
    () => tasks.filter((t) => t.status === 'arbitrating') as TaskDetail[],
    [tasks],
  )

  // Auto-register arbiters
  useEffect(() => {
    async function init() {
      const ids: string[] = []
      for (let i = 0; i < DEV_ARBITERS.length; i++) {
        const a = DEV_ARBITERS[i]
        const addr = arbiterAddresses[i]
        let id = localStorage.getItem(a.storageKey)
        if (!id && addr) {
          try {
            const user = await registerUser({ nickname: a.nickname, wallet: addr, role: 'worker' })
            id = user.id
            localStorage.setItem(a.storageKey, id)
          } catch {
            try {
              const resp = await fetch(`/api/users?nickname=${a.nickname}`)
              if (resp.ok) {
                const u = await resp.json()
                id = u.id
                localStorage.setItem(a.storageKey, id!)
              }
            } catch {
              id = localStorage.getItem(a.storageKey)
            }
          }
        }
        ids.push(id || '')
      }
      setArbiterIds(ids)
    }
    init().catch(console.error)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function refreshBalance() {
    const addr = arbiterAddresses[activeIdx]
    if (!addr) return
    setBalRefreshing(true)
    try {
      const bal = await fetchUsdcBalance(addr)
      setBalances((prev) => { const next = [...prev]; next[activeIdx] = bal; return next })
    } catch {
      setBalances((prev) => { const next = [...prev]; next[activeIdx] = 'error'; return next })
    } finally {
      setBalRefreshing(false)
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshBalance() }, [activeIdx])

  const activeArbiter = DEV_ARBITERS[activeIdx]
  const activeArbiterId = arbiterIds[activeIdx] || ''

  if (DEV_ARBITERS.length === 0) {
    return (
      <div>
        <h2 className="text-base font-semibold mb-5">Arbiter Panel</h2>
        <p className="text-xs text-muted-foreground">
          No arbiter wallet keys configured. Set NEXT_PUBLIC_DEV_ARBITER1_WALLET_KEY in .env.local
        </p>
      </div>
    )
  }

  return (
    <div>
      <h2 className="text-base font-semibold mb-5">Arbiter Panel</h2>

      {/* Arbiter selector */}
      <div className="flex flex-col gap-1.5 mb-4">
        <Label>Active Arbiter</Label>
        <Select
          value={String(activeIdx)}
          onValueChange={(v) => setActiveIdx(parseInt(v, 10))}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DEV_ARBITERS.map((a, i) => (
              <SelectItem key={a.storageKey} value={String(i)}>
                {a.nickname}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Arbiter info */}
      <div className="relative mb-4 p-3 bg-zinc-900 border border-zinc-700 rounded text-sm">
        <button
          onClick={refreshBalance}
          disabled={balRefreshing}
          className="absolute top-2 right-2 text-muted-foreground hover:text-white disabled:opacity-40"
          title="Refresh balance"
        >
          ↻
        </button>
        <p className="text-muted-foreground mb-1">{activeArbiter?.nickname}</p>
        <p className="font-mono text-xs break-all">{arbiterAddresses[activeIdx] ?? '\u2014'}</p>
        <p className="text-xs text-muted-foreground mt-1">
          Balance: <span className="text-white">{balances[activeIdx]} USDC</span>
        </p>
        {activeArbiterId ? (
          <>
            <p className="text-xs text-muted-foreground mt-1">
              ID: <span className="font-mono text-white break-all">{activeArbiterId}</span>
            </p>
            <div className="mt-1">
              <ArbiterInfo userId={activeArbiterId} />
            </div>
          </>
        ) : (
          <p className="text-xs text-yellow-400 mt-1">Not registered yet</p>
        )}
      </div>

      {/* Pending arbitration tasks */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">
          Tasks in Arbitration ({arbitratingTasks.length})
        </h3>
        <button
          onClick={() => setPollKey((k) => k + 1)}
          className="text-xs text-muted-foreground hover:text-white"
          title="Refresh"
        >
          ↻ Refresh
        </button>
      </div>

      {arbitratingTasks.length === 0 && (
        <p className="text-xs text-muted-foreground py-4 text-center">
          No tasks in arbitration
        </p>
      )}

      <div className="space-y-3" key={pollKey}>
        {arbitratingTasks.map((task) => (
          <TaskVoteSection
            key={task.id}
            task={task}
            arbiterId={activeArbiterId}
            onVoted={() => setPollKey((k) => k + 1)}
          />
        ))}
      </div>
    </div>
  )
}
