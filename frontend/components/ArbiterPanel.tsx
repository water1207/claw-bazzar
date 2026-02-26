'use client'

import { useState, useMemo, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  useTasks, useArbiterVotes, submitArbiterVote, registerUser, useUser,
} from '@/lib/api'
import type { ChallengeVerdict } from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'
import { getDevWalletAddress } from '@/lib/x402'
import { fetchUsdcBalance } from '@/lib/utils'
import type { Hex } from 'viem'

interface ArbiterDef {
  key: Hex
  nickname: string
  storageKey: string
}

const DEV_ARBITERS: ArbiterDef[] = [
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER1_WALLET_KEY as Hex, nickname: 'arbiter-alpha', storageKey: 'devArbiter1Id' },
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER2_WALLET_KEY as Hex, nickname: 'arbiter-beta', storageKey: 'devArbiter2Id' },
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER3_WALLET_KEY as Hex, nickname: 'arbiter-gamma', storageKey: 'devArbiter3Id' },
].filter((a) => a.key)

const EMPTY_TASKS: never[] = []

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

function ChallengeVoteCard({ challengeId, arbiterId, onVoted }: {
  challengeId: string
  arbiterId: string
  onVoted: () => void
}) {
  const { data: votes = [], mutate } = useArbiterVotes(challengeId, arbiterId)
  const [verdict, setVerdict] = useState<ChallengeVerdict | ''>('')
  const [feedback, setFeedback] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const myVote = votes.find((v) => v.arbiter_user_id === arbiterId)
  const votedCount = votes.filter((v) => v.vote !== null).length

  async function handleVote(e: React.FormEvent) {
    e.preventDefault()
    if (!verdict || !feedback) return
    setError(null)
    setSubmitting(true)
    try {
      await submitArbiterVote(challengeId, {
        arbiter_user_id: arbiterId,
        verdict,
        feedback,
      })
      setVerdict('')
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
    <div className="p-3 bg-zinc-900 border border-zinc-700 rounded space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-muted-foreground" title={challengeId}>
          Challenge: {challengeId.slice(0, 8)}...
        </span>
        <span className="text-xs text-muted-foreground">{votedCount}/{votes.length} voted</span>
      </div>

      {/* Vote status list */}
      <div className="space-y-1">
        {votes.map((v) => (
          <div key={v.id} className="flex items-center justify-between text-xs">
            <span className={`font-mono ${v.arbiter_user_id === arbiterId ? 'text-blue-400' : 'text-muted-foreground'}`}>
              {v.arbiter_user_id === arbiterId ? '(you)' : v.arbiter_user_id.slice(0, 8) + '...'}
            </span>
            {v.vote ? (
              <div className="flex items-center gap-1.5">
                <VerdictBadge verdict={v.vote} />
                {v.feedback && (
                  <span className="text-muted-foreground max-w-[120px] truncate" title={v.feedback}>
                    {v.feedback}
                  </span>
                )}
              </div>
            ) : (
              <span className="text-yellow-400">pending...</span>
            )}
          </div>
        ))}
      </div>

      {/* Vote form - only show if this arbiter hasn't voted yet */}
      {myVote && !myVote.vote && (
        <form onSubmit={handleVote} className="flex flex-col gap-2 pt-2 border-t border-zinc-700">
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
            placeholder="Reasoning (required)"
            rows={2}
            className="text-xs"
            required
          />
          <Button type="submit" size="sm" disabled={submitting || !verdict || !feedback}>
            {submitting ? 'Voting...' : 'Submit Vote'}
          </Button>
          {error && <p className="text-xs text-red-400 break-all">{error}</p>}
        </form>
      )}

      {myVote?.vote && (
        <p className="text-xs text-green-400 pt-1 border-t border-zinc-700">You voted: {myVote.vote}</p>
      )}

      {!myVote && votes.length > 0 && (
        <p className="text-xs text-muted-foreground pt-1 border-t border-zinc-700">
          Not assigned to this challenge
        </p>
      )}
    </div>
  )
}

export function ArbiterPanel() {
  const [activeIdx, setActiveIdx] = useState(0)
  const [arbiterIds, setArbiterIds] = useState<string[]>(() => DEV_ARBITERS.map(() => ''))
  const [challenges, setChallenges] = useState<Array<{ challenge_id: string; task_id: string; task_title: string }>>([])
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
  const arbitratingTasks = useMemo(() => tasks.filter((t) => t.status === 'arbitrating'), [tasks])

  // Auto-register arbiters (reuse existing DB users)
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
            // Already exists — fetch by trying to get from API
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

  // Fetch challenges for arbitrating tasks
  useEffect(() => {
    async function fetchChallenges() {
      const results: typeof challenges = []
      for (const task of arbitratingTasks) {
        try {
          const resp = await fetch(`/api/tasks/${task.id}/challenges`)
          if (resp.ok) {
            const chs = await resp.json()
            for (const c of chs) {
              results.push({ challenge_id: c.id, task_id: task.id, task_title: task.title })
            }
          }
        } catch {}
      }
      setChallenges(results)
    }
    fetchChallenges()
  }, [arbitratingTasks, pollKey])

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
        <p className="font-mono text-xs break-all">{arbiterAddresses[activeIdx] ?? '—'}</p>
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

      {/* Pending challenges */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">
          Pending Challenges ({challenges.length})
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

      <div className="space-y-3">
        {challenges.map((c) => (
          <div key={c.challenge_id}>
            <p className="text-xs text-muted-foreground mb-1">
              Task: <span className="text-white">{c.task_title}</span>
            </p>
            <ChallengeVoteCard
              challengeId={c.challenge_id}
              arbiterId={activeArbiterId}
              onVoted={() => setPollKey((k) => k + 1)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
