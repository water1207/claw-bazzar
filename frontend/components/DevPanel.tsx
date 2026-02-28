'use client'

import { useState, useMemo, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { createTask, createSubmission, registerUser, createChallenge, useUser } from '@/lib/api'
import type { UserRole, Task, Submission, TaskDetail, Challenge } from '@/lib/api'
import { signX402Payment, getDevWalletAddress } from '@/lib/x402'
import { signChallengePermit } from '@/lib/permit'
import { fetchUsdcBalance } from '@/lib/utils'
import { ArbiterPanel } from '@/components/ArbiterPanel'
import { BalanceTrustHistoryPanel } from '@/components/BalanceTrustHistoryPanel'
import { TrustBadge } from '@/components/TrustBadge'
import { TaskStatusStepper } from '@/components/TaskStatusStepper'
import { FeedbackCard } from '@/components/FeedbackCard'
import type { Hex } from 'viem'
import { DEV_PUBLISHER, DEV_WORKERS } from '@/lib/dev-wallets'

const PLATFORM_WALLET = process.env.NEXT_PUBLIC_PLATFORM_WALLET as Hex | undefined
const ESCROW_ADDRESS = process.env.NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS || ''

const PRESETS = [
  { label: '1h', value: '1', unit: 'hours' },
  { label: '6h', value: '6', unit: 'hours' },
  { label: '12h', value: '12', unit: 'hours' },
  { label: '1d', value: '1', unit: 'days' },
  { label: '3d', value: '3', unit: 'days' },
  { label: '7d', value: '7', unit: 'days' },
] as const

function useCountdown(target: string | null | undefined): string {
  const [display, setDisplay] = useState('')

  useEffect(() => {
    if (!target) return
    const update = () => {
      const diff = new Date(target).getTime() - Date.now()
      if (diff <= 0) {
        setDisplay('已截止')
        return
      }
      const h = Math.floor(diff / 3_600_000)
      const m = Math.floor((diff % 3_600_000) / 60_000)
      const s = Math.floor((diff % 60_000) / 1_000)
      if (h > 0) setDisplay(`${h}小时${m}分钟后到期`)
      else if (m > 0) setDisplay(`${m}分${s}秒后到期`)
      else setDisplay(`${s}秒后到期`)
    }
    update()
    const id = setInterval(update, 1000)
    return () => clearInterval(id)
  }, [target])

  return display
}

function UserTrustLine({ userId }: { userId: string }) {
  const { data: user } = useUser(userId)
  if (!user) return null
  return (
    <div className="flex items-center gap-1.5 mt-1">
      <span className="text-xs text-muted-foreground">{user.nickname}</span>
      <TrustBadge tier={user.trust_tier} score={user.trust_score} />
    </div>
  )
}

function WalletCard({
  label, address, id, balance, onRefresh, refreshing, showFundLink,
}: {
  label: string
  address: string | null
  id: string
  balance: string
  onRefresh: () => void
  refreshing: boolean
  showFundLink?: boolean
}) {
  return (
    <div className="relative mb-4 p-3 bg-zinc-900 border border-zinc-700 rounded text-sm">
      <button
        onClick={onRefresh}
        disabled={refreshing}
        className="absolute top-2 right-2 text-muted-foreground hover:text-white disabled:opacity-40"
        title="Refresh balance"
      >
        ↻
      </button>
      <p className="text-muted-foreground mb-1">{label}</p>
      <p className="font-mono text-xs break-all">{address ?? '—'}</p>
      <p className="text-xs text-muted-foreground mt-1">
        Balance: <span className="text-white">{balance} USDC</span>
      </p>
      {id && (
        <>
          <p className="text-xs text-muted-foreground mt-0.5">
            ID: <span className="font-mono text-white break-all">{id}</span>
          </p>
          <UserTrustLine userId={id} />
        </>
      )}
      {showFundLink && (
        <a
          href="https://faucet.circle.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 text-xs hover:underline mt-1 inline-block"
        >
          Fund with testnet USDC
        </a>
      )}
    </div>
  )
}

interface OracleLog {
  timestamp: string
  mode: string
  task_id: string
  task_title: string
  submission_id: string
  worker_id: string
  worker_nickname: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  duration_ms: number
}

interface TaskGroup {
  task_id: string
  task_title: string
  model: string
  total_tokens: number
  total_duration_ms: number
  entries: OracleLog[]
  /** Grouped by worker_id ('' key = task-level calls) */
  byWorker: Map<string, { nickname: string; submission_id: string; logs: OracleLog[]; tokens: number }>
}

function groupByTask(logs: OracleLog[]): TaskGroup[] {
  const map = new Map<string, TaskGroup>()
  // logs are already newest-first; reverse to build groups chronologically then reverse groups
  const chronological = [...logs].reverse()
  for (const log of chronological) {
    const key = log.task_id || '__no_task__'
    if (!map.has(key)) {
      map.set(key, {
        task_id: log.task_id,
        task_title: log.task_title,
        model: log.model,
        total_tokens: 0,
        total_duration_ms: 0,
        entries: [],
        byWorker: new Map(),
      })
    }
    const g = map.get(key)!
    g.total_tokens += log.total_tokens
    g.total_duration_ms += log.duration_ms
    g.entries.push(log)

    const wk = log.worker_id || ''
    if (!g.byWorker.has(wk)) {
      g.byWorker.set(wk, {
        nickname: log.worker_nickname || '',
        submission_id: log.submission_id || '',
        logs: [],
        tokens: 0,
      })
    }
    const w = g.byWorker.get(wk)!
    w.logs.push(log)
    w.tokens += log.total_tokens
  }
  return Array.from(map.values()).reverse()
}

function formatDuration(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function OracleLogsPanel() {
  const [logs, setLogs] = useState<OracleLog[]>([])
  const [collapsed, setCollapsed] = useState(false)
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const resp = await fetch('/api/internal/oracle-logs')
        if (resp.ok) setLogs(await resp.json())
      } catch {}
    }
    fetchLogs()
    const id = setInterval(fetchLogs, 5000)
    return () => clearInterval(id)
  }, [])

  const groups = useMemo(() => groupByTask(logs), [logs])
  const globalTotal = logs.reduce((s, l) => s + l.total_tokens, 0)

  function toggleTask(taskId: string) {
    setExpandedTasks(prev => {
      const next = new Set(prev)
      if (next.has(taskId)) next.delete(taskId)
      else next.add(taskId)
      return next
    })
  }

  return (
    <div className="col-span-4 mt-6 border-t border-zinc-700 pt-6">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 text-base font-semibold mb-4 hover:text-blue-400"
      >
        <span className="text-xs">{collapsed ? '▶' : '▼'}</span>
        Oracle Logs
        <span className="text-xs text-muted-foreground font-normal ml-1">
          {logs.length} calls · {globalTotal.toLocaleString()} tokens
        </span>
      </button>
      {!collapsed && (
        <div className="space-y-3">
          {groups.length === 0 ? (
            <p className="text-xs text-muted-foreground py-4 text-center">No oracle logs yet</p>
          ) : groups.map((g) => {
            const key = g.task_id || '__no_task__'
            const expanded = expandedTasks.has(key)
            return (
              <div key={key} className="border border-zinc-700 rounded overflow-hidden">
                {/* Task header */}
                <button
                  onClick={() => toggleTask(key)}
                  className="w-full flex items-center justify-between px-3 py-2 bg-zinc-900 hover:bg-zinc-800 text-left text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[10px] text-muted-foreground">{expanded ? '▼' : '▶'}</span>
                    <span className="text-white font-medium truncate">{g.task_title || g.task_id || 'Unknown task'}</span>
                    <span className="text-muted-foreground shrink-0">({g.entries.length} calls)</span>
                  </div>
                  <div className="flex items-center gap-4 shrink-0 ml-4">
                    <span className="text-muted-foreground">{g.model}</span>
                    <span className="font-mono text-white">{g.total_tokens.toLocaleString()} tok</span>
                    <span className="font-mono text-muted-foreground">{formatDuration(g.total_duration_ms)}</span>
                  </div>
                </button>

                {/* Expanded: group by worker */}
                {expanded && (
                  <div className="divide-y divide-zinc-800">
                    {Array.from(g.byWorker.entries()).map(([wk, wInfo]) => (
                      <div key={wk || '__task__'} className="px-3 py-2">
                        {/* Worker/submission header */}
                        {wk ? (
                          <div className="flex items-center gap-2 mb-1.5 text-xs">
                            <span className="px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300 font-medium">
                              {wInfo.nickname || wk.slice(0, 8)}
                            </span>
                            {wInfo.submission_id && (
                              <span className="text-muted-foreground font-mono" title={wInfo.submission_id}>
                                Sub: {wInfo.submission_id.slice(0, 8)}...
                              </span>
                            )}
                            <span className="text-muted-foreground ml-auto font-mono">
                              {wInfo.tokens.toLocaleString()} tok
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 mb-1.5 text-xs">
                            <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">Task-level</span>
                            <span className="text-muted-foreground ml-auto font-mono">
                              {wInfo.tokens.toLocaleString()} tok
                            </span>
                          </div>
                        )}
                        {/* Individual log rows */}
                        <div className="space-y-0.5">
                          {wInfo.logs.map((log, i) => (
                            <div key={i} className="flex items-center gap-3 text-[11px] pl-2 py-0.5 hover:bg-zinc-900/50 rounded">
                              <span className="font-mono text-muted-foreground w-16 shrink-0">
                                {new Date(log.timestamp).toLocaleTimeString()}
                              </span>
                              <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-white shrink-0">
                                {log.mode}
                              </span>
                              <span className="text-muted-foreground ml-auto tabular-nums">
                                {log.prompt_tokens.toLocaleString()}
                                <span className="text-zinc-600 mx-0.5">/</span>
                                {log.completion_tokens.toLocaleString()}
                                <span className="text-zinc-600 mx-0.5">/</span>
                                <span className="text-white">{log.total_tokens.toLocaleString()}</span>
                              </span>
                              <span className="font-mono text-muted-foreground w-14 text-right shrink-0">
                                {formatDuration(log.duration_ms)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function statusColor(status: Submission['status']): string {
  switch (status) {
    case 'scored': return 'text-green-400'
    case 'gate_passed': return 'text-blue-400'
    case 'gate_failed': return 'text-red-400'
    case 'policy_violation': return 'text-orange-400'
    default: return 'text-yellow-400'
  }
}

function statusLabel(status: Submission['status']): string {
  switch (status) {
    case 'scored': return '已评分'
    case 'gate_passed': return 'Gate ✓'
    case 'gate_failed': return 'Gate ✗'
    case 'policy_violation': return '违规'
    default: return '评分中…'
  }
}

interface WorkerSubRowProps {
  worker: import('@/lib/dev-wallets').DevUser
  sub: Submission
  isActive: boolean
  maxRevisions: number | null
  onClick: () => void
}

function WorkerSubRow({ worker, sub, isActive, maxRevisions, onClick }: WorkerSubRowProps) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div
      className={['px-3 py-2 cursor-pointer hover:bg-zinc-900/60', isActive ? 'bg-zinc-900/40' : ''].join(' ')}
      onClick={onClick}
    >
      <div className="flex items-center gap-2">
        <span className={['font-medium w-16 shrink-0 text-xs', isActive ? 'text-blue-300' : 'text-white'].join(' ')}>
          {worker.nickname}
        </span>
        <span className={['font-medium text-xs shrink-0', statusColor(sub.status)].join(' ')}>
          {statusLabel(sub.status)}
        </span>
        {sub.score !== null && (
          <span className="font-mono text-white text-xs shrink-0">{sub.score.toFixed(1)}</span>
        )}
        <span className="text-muted-foreground font-mono text-[11px] truncate flex-1" title={sub.id}>
          {sub.id.slice(0, 8)}…
        </span>
        {maxRevisions && (
          <span className="text-muted-foreground text-[11px] shrink-0">r{sub.revision}/{maxRevisions}</span>
        )}
        {sub.oracle_feedback && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            className="text-muted-foreground hover:text-white text-[11px] shrink-0 ml-1"
          >
            {expanded ? '▲' : '▼'}
          </button>
        )}
      </div>
      {expanded && sub.oracle_feedback && (
        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
          <FeedbackCard raw={sub.oracle_feedback} />
        </div>
      )}
    </div>
  )
}

export function DevPanel() {
  const publisherAddress = useMemo(() => {
    if (!DEV_PUBLISHER?.key) return null
    try { return getDevWalletAddress(DEV_PUBLISHER.key) } catch { return null }
  }, [])

  const workerAddresses = useMemo(
    () => DEV_WORKERS.map((w) => {
      try { return getDevWalletAddress(w.key) } catch { return null }
    }),
    [],
  )

  const [activeWorkerIdx, setActiveWorkerIdx] = useState(0)
  const activeWorker = DEV_WORKERS[activeWorkerIdx]
  const activeWorkerAddress = workerAddresses[activeWorkerIdx] ?? null

  const envError = !DEV_PUBLISHER?.key || !PLATFORM_WALLET

  // Register form state
  const [nickname, setNickname] = useState('')
  const [wallet, setWallet] = useState('')
  const [role, setRole] = useState<UserRole>('publisher')
  const [registerMsg, setRegisterMsg] = useState<string | null>(null)

  // Publish form state
  const [publisherId, setPublisherId] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState<'fastest_first' | 'quality_first'>('fastest_first')
  const [threshold, setThreshold] = useState('0.8')
  const [maxRevisions, setMaxRevisions] = useState('')
  const [deadlineDuration, setDeadlineDuration] = useState('5')
  const [deadlineUnit, setDeadlineUnit] = useState<'minutes' | 'hours' | 'days'>('minutes')
  const [challengeDuration, setChallengeDuration] = useState('')
  const [criteria, setCriteria] = useState<string[]>([''])
  const [bounty, setBounty] = useState('0.01')
  const [publishing, setPublishing] = useState(false)
  const [publishedTask, setPublishedTask] = useState<Task | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)

  // Submit form state
  const [taskId, setTaskId] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [content, setContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [workerSubs, setWorkerSubs] = useState<Record<string, Submission>>({})
  const [polledTask, setPolledTask] = useState<TaskDetail | null>(null)
  const [isPolling, setIsPolling] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Challenge form state
  const [challengeTaskId, setChallengeTaskId] = useState('')
  const [challengeSubId, setChallengeSubId] = useState('')
  const [challengeReason, setChallengeReason] = useState('')
  const [challenging, setChallenging] = useState(false)
  const [challengeResult, setChallengeResult] = useState<Challenge | null>(null)
  const [challengeError, setChallengeError] = useState<string | null>(null)

  // Balance state
  const [pubBalance, setPubBalance] = useState('...')
  const [wrkBalances, setWrkBalances] = useState<string[]>(() => DEV_WORKERS.map(() => '...'))
  const [pubRefreshing, setPubRefreshing] = useState(false)
  const [wrkRefreshing, setWrkRefreshing] = useState(false)

  // Worker IDs (one per worker)
  const [workerIds, setWorkerIds] = useState<string[]>(() => DEV_WORKERS.map(() => ''))

  // Auto-detect submission ID for challenge
  useEffect(() => {
    if (!challengeTaskId) { setChallengeSubId(''); return }
    const wId = workerIds[activeWorkerIdx]
    if (!wId) { setChallengeSubId(''); return }
    let cancelled = false
    fetch(`/api/tasks/${challengeTaskId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((task: TaskDetail | null) => {
        if (cancelled || !task) return
        const sub = task.submissions.find((s) => s.worker_id === wId)
        setChallengeSubId(sub?.id ?? '')
      })
      .catch(() => { if (!cancelled) setChallengeSubId('') })
    return () => { cancelled = true }
  }, [challengeTaskId, activeWorkerIdx, workerIds])

  // Countdowns
  const deadlineCountdown = useCountdown(publishedTask?.deadline)

  async function refreshPubBalance() {
    if (!publisherAddress) return
    setPubRefreshing(true)
    try {
      setPubBalance(await fetchUsdcBalance(publisherAddress))
    } catch {
      setPubBalance('error')
    } finally {
      setPubRefreshing(false)
    }
  }

  async function refreshWrkBalance() {
    const addr = activeWorkerAddress
    if (!addr) return
    setWrkRefreshing(true)
    try {
      const bal = await fetchUsdcBalance(addr)
      setWrkBalances((prev) => {
        const next = [...prev]
        next[activeWorkerIdx] = bal
        return next
      })
    } catch {
      setWrkBalances((prev) => {
        const next = [...prev]
        next[activeWorkerIdx] = 'error'
        return next
      })
    } finally {
      setWrkRefreshing(false)
    }
  }

  async function autoRegister() {
    // Helper: resolve a user ID — validate cached, else register or fetch by nickname
    // Returns { id, isNew } where isNew=true only when freshly registered
    async function resolveUser(
      storageKey: string, nickname: string, wallet: string, role: UserRole,
    ): Promise<{ id: string; isNew: boolean } | null> {
      // Check if cached ID is still valid
      const cached = localStorage.getItem(storageKey)
      if (cached) {
        try {
          const resp = await fetch(`/api/users/${cached}`)
          if (resp.ok) return { id: cached, isNew: false }
        } catch {}
        localStorage.removeItem(storageKey)
      }
      // Register new or fetch existing by nickname
      try {
        const user = await registerUser({ nickname, wallet, role })
        localStorage.setItem(storageKey, user.id)
        return { id: user.id, isNew: true }
      } catch {
        try {
          const resp = await fetch(`/api/users?nickname=${nickname}`)
          if (resp.ok) {
            const u = await resp.json()
            localStorage.setItem(storageKey, u.id)
            return { id: u.id, isNew: false }
          }
        } catch {}
      }
      return null
    }

    // Helper: set initial trust score (only for newly registered users)
    async function initTrustScore(userId: string, score: number) {
      try {
        await fetch(`/api/internal/users/${userId}/trust`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ score }),
        })
      } catch {}
    }

    // Publisher
    let pubId: string | null = null
    if (DEV_PUBLISHER) {
      const result = await resolveUser(DEV_PUBLISHER.storageKey, DEV_PUBLISHER.nickname, publisherAddress!, 'publisher')
      if (result) {
        pubId = result.id
        if (result.isNew) await initTrustScore(pubId, DEV_PUBLISHER.trustScore ?? 850)
      }
    }
    if (pubId) setPublisherId(pubId)

    const ids: string[] = []
    for (let i = 0; i < DEV_WORKERS.length; i++) {
      const w = DEV_WORKERS[i]
      const addr = workerAddresses[i]
      let wrkId: string | null = null
      if (addr) {
        const result = await resolveUser(w.storageKey, w.nickname, addr, 'worker')
        if (result) {
          wrkId = result.id
          if (result.isNew) await initTrustScore(wrkId, w.trustScore ?? 500)
        }
      }
      ids.push(wrkId || '')
    }
    setWorkerIds(ids)
    if (ids[0]) setWorkerId(ids[0])
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { autoRegister().catch(console.error) }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshPubBalance() }, [publisherAddress])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshWrkBalance() }, [activeWorkerIdx])

  // Poll task submissions whenever isPolling=true and taskId is set
  useEffect(() => {
    if (!isPolling || !taskId) return

    const TERMINAL = new Set<Submission['status']>(['scored', 'gate_failed', 'policy_violation'])

    const tick = async () => {
      try {
        const resp = await fetch(`/api/tasks/${taskId}`)
        if (!resp.ok) return
        const task: TaskDetail = await resp.json()
        setPolledTask(task)

        setWorkerSubs(prev => {
          const next = { ...prev }
          for (let i = 0; i < DEV_WORKERS.length; i++) {
            const w = DEV_WORKERS[i]
            const wId = workerIds[i]
            if (!wId) continue
            const found = task.submissions.find(s => s.worker_id === wId)
            if (found) next[w.storageKey] = found
          }
          return next
        })

        // Stop polling when all tracked subs have reached a terminal state
        // (gate_passed is terminal for quality_first — batch scoring continues on backend)
        setWorkerSubs(current => {
          const allDone = Object.keys(current).length > 0 &&
            Object.values(current).every(
              s => TERMINAL.has(s.status) || s.status === 'gate_passed'
            )
          if (allDone) setIsPolling(false)
          return current
        })
      } catch {}
    }

    tick()
    const id = setInterval(tick, 2000)
    return () => clearInterval(id)
  }, [isPolling, taskId, workerIds])

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setRegisterMsg(null)
    try {
      const user = await registerUser({ nickname, wallet, role })
      setRegisterMsg(`Registered: ${user.id}`)
      if (role === 'publisher') {
        setPublisherId(user.id)
      } else {
        setWorkerId(user.id)
      }
      setNickname('')
      setWallet('')
    } catch (err) {
      setRegisterMsg(`Error: ${(err as Error).message}`)
    }
  }

  function computeDeadlineISO(): string {
    const n = parseFloat(deadlineDuration)
    if (!Number.isFinite(n) || n <= 0) {
      throw new Error('Deadline duration must be a positive number')
    }
    const ms = n * (deadlineUnit === 'days' ? 86_400_000 : deadlineUnit === 'hours' ? 3_600_000 : 60_000)
    return new Date(Date.now() + ms).toISOString()
  }

  async function handlePublish(e: React.FormEvent) {
    e.preventDefault()
    setPublishError(null)
    setPublishedTask(null)
    setPublishing(true)

    try {
      const bountyAmount = bounty ? parseFloat(bounty) : 0
      let paymentHeader: string | undefined
      if (bountyAmount > 0) {
        if (!DEV_PUBLISHER?.key || !PLATFORM_WALLET) {
          setPublishError('Error: DEV_PUBLISHER_WALLET_KEY or PLATFORM_WALLET env vars not set')
          return
        }
        paymentHeader = await signX402Payment({
          privateKey: DEV_PUBLISHER.key,
          payTo: PLATFORM_WALLET,
          amount: bountyAmount,
        })
      }

      const task = await createTask(
        {
          title,
          description,
          type,
          threshold: threshold ? parseFloat(threshold) : null,
          max_revisions: maxRevisions ? parseInt(maxRevisions, 10) : null,
          deadline: computeDeadlineISO(),
          publisher_id: publisherId || null,
          bounty: bountyAmount,
          challenge_duration: challengeDuration ? parseInt(challengeDuration, 10) : null,
          acceptance_criteria: criteria.map((s) => s.trim()).filter(Boolean),
        },
        paymentHeader,
      )
      setPublishedTask(task)
      setTaskId(task.id)
      setTitle('')
      setDescription('')
      setThreshold('0.8')
      setMaxRevisions('')
      setChallengeDuration('')
      setCriteria([''])
      setBounty('')
    } catch (err) {
      setPublishError((err as Error).message)
    } finally {
      setPublishing(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitError(null)
    setSubmitting(true)
    try {
      const sub = await createSubmission(taskId, { worker_id: workerId, content })
      setWorkerSubs(prev => ({ ...prev, [activeWorker!.storageKey]: sub }))
      setContent('')
      setChallengeTaskId(taskId)
      setChallengeSubId(sub.id)
      setIsPolling(true)
    } catch (err) {
      setSubmitError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleChallenge(e: React.FormEvent) {
    e.preventDefault()
    setChallengeError(null)
    setChallengeResult(null)
    setChallenging(true)
    try {
      const workerKey = activeWorker?.key
      if (ESCROW_ADDRESS && workerKey) {
        // Fetch actual task to get correct bounty for deposit calculation
        const taskResp = await fetch(`/api/tasks/${challengeTaskId}`)
        if (!taskResp.ok) throw new Error('Failed to fetch task details')
        const challengeTask: TaskDetail = await taskResp.json()
        const bountyAmount = challengeTask.bounty ?? 0

        // Fetch worker trust tier to determine deposit rate (S=5%, A=10%, B=30%)
        const wId = workerIds[activeWorkerIdx]
        let depositRate = 0.10 // default A-tier
        if (wId) {
          try {
            const userResp = await fetch(`/api/users/${wId}`)
            if (userResp.ok) {
              const userData = await userResp.json()
              const tier = userData.trust_tier
              if (tier === 'S') depositRate = 0.05
              else if (tier === 'A') depositRate = 0.10
              else if (tier === 'B') depositRate = 0.30
            }
          } catch { /* use default */ }
        }
        const depositAmount = challengeTask.submission_deposit ?? bountyAmount * depositRate
        const totalAmount = depositAmount + 0.01 // + service fee

        const permit = await signChallengePermit({
          privateKey: workerKey,
          spender: ESCROW_ADDRESS,
          amount: totalAmount,
        })

        const result = await createChallenge(challengeTaskId, {
          challenger_submission_id: challengeSubId,
          reason: challengeReason,
          challenger_wallet: getDevWalletAddress(workerKey),
          permit_deadline: permit.deadline,
          permit_v: permit.v,
          permit_r: permit.r,
          permit_s: permit.s,
        })
        setChallengeResult(result)
      } else {
        const result = await createChallenge(challengeTaskId, {
          challenger_submission_id: challengeSubId,
          reason: challengeReason,
        })
        setChallengeResult(result)
      }
      setChallengeReason('')
    } catch (err) {
      setChallengeError((err as Error).message)
    } finally {
      setChallenging(false)
    }
  }

  return (
    <div className="grid grid-cols-4 gap-10 p-8 max-w-[1600px] mx-auto">
      {/* Register User */}
      <div>
        <h2 className="text-base font-semibold mb-5">Register User</h2>
        <form onSubmit={handleRegister} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Nickname</Label>
            <Input
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              required
              placeholder="alice"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Wallet Address</Label>
            <Input
              value={wallet}
              onChange={(e) => setWallet(e.target.value)}
              required
              placeholder="0x..."
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Role</Label>
            <Select
              value={role}
              onValueChange={(v) => setRole(v as UserRole)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="publisher">publisher</SelectItem>
                <SelectItem value="worker">worker</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Button type="submit">Register</Button>

          {registerMsg && (
            <p className="text-sm font-mono break-all">{registerMsg}</p>
          )}
        </form>
      </div>

      {/* Publish Task */}
      <div>
        <h2 className="text-base font-semibold mb-5">Publish Task</h2>

        <WalletCard
          label="Publisher Wallet"
          address={publisherAddress}
          id={publisherId}
          balance={pubBalance}
          onRefresh={refreshPubBalance}
          refreshing={pubRefreshing}
          showFundLink
        />

        {envError && (
          <div className="mb-4 p-3 bg-red-950 border border-red-800 rounded text-sm text-red-300">
            Missing env vars: set <code>NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY</code> and{' '}
            <code>NEXT_PUBLIC_PLATFORM_WALLET</code> in <code>frontend/.env.local</code>
          </div>
        )}

        <form onSubmit={handlePublish} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Publisher ID</Label>
            <Input
              value={publisherId}
              onChange={(e) => setPublisherId(e.target.value)}
              placeholder="Auto-filled after register"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Title</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="Task title"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              rows={3}
              placeholder="Describe the task requirements"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Acceptance Criteria{' '}
              <span className="text-muted-foreground text-xs">(Oracle V3 gate check + scoring dimensions)</span>
            </Label>
            <div className="flex flex-col gap-1.5">
              {criteria.map((item, idx) => (
                <div key={idx} className="flex gap-1.5 items-center">
                  <span className="text-muted-foreground text-xs w-4 shrink-0 text-right">{idx + 1}.</span>
                  <Input
                    value={item}
                    onChange={(e) => {
                      const next = [...criteria]
                      next[idx] = e.target.value
                      setCriteria(next)
                    }}
                    placeholder="验收标准条目"
                    className="flex-1 text-sm"
                  />
                  {criteria.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setCriteria(criteria.filter((_, i) => i !== idx))}
                      className="text-muted-foreground hover:text-red-400 text-sm w-5 shrink-0"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setCriteria([...criteria, ''])}
                className="text-xs text-blue-400 hover:text-blue-300 text-left mt-0.5 pl-5"
              >
                + Add criterion
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Type</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as typeof type)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fastest_first">fastest_first</SelectItem>
                <SelectItem value="quality_first">quality_first</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Bounty (USDC){' '}
              <span className="text-muted-foreground text-xs">(optional)</span>
            </Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              placeholder="10.00"
              value={bounty}
              onChange={(e) => setBounty(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Threshold{' '}
              <span className="text-muted-foreground text-xs">(fastest_first only)</span>
            </Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              max="1"
              placeholder="0.8"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Max Revisions{' '}
              <span className="text-muted-foreground text-xs">(quality_first only)</span>
            </Label>
            <Input
              type="number"
              min="1"
              placeholder="3"
              value={maxRevisions}
              onChange={(e) => setMaxRevisions(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Challenge Duration{' '}
              <span className="text-muted-foreground text-xs">(quality_first, 秒, 默认7200)</span>
            </Label>
            <Input
              type="number"
              min="60"
              placeholder="7200"
              value={challengeDuration}
              onChange={(e) => setChallengeDuration(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Deadline</Label>
            <div className="flex gap-2">
              <Input
                type="number"
                min="1"
                value={deadlineDuration}
                onChange={(e) => setDeadlineDuration(e.target.value)}
                className="w-20"
              />
              <Select
                value={deadlineUnit}
                onValueChange={(v) => setDeadlineUnit(v as typeof deadlineUnit)}
              >
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="minutes">Minutes</SelectItem>
                  <SelectItem value="hours">Hours</SelectItem>
                  <SelectItem value="days">Days</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-1 flex-wrap">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => { setDeadlineDuration(p.value); setDeadlineUnit(p.unit) }}
                  className="text-xs px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-muted-foreground hover:text-white"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <Button type="submit" disabled={envError || publishing}>
            {publishing ? (
              <span className="flex items-center gap-2">
                <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Publishing…
              </span>
            ) : 'Publish'}
          </Button>

          {publishError && (
            <p className="text-sm text-red-400 break-all">{publishError}</p>
          )}

          {publishedTask && (
            <div className="p-3 bg-zinc-900 border border-zinc-700 rounded text-xs space-y-1">
              <p className="text-green-400 font-medium">Task published</p>
              <p className="text-muted-foreground">
                Status: <span className="text-white">{publishedTask.status}</span>
              </p>
              <TaskStatusStepper type={publishedTask.type} status={publishedTask.status} />
              <p className="text-muted-foreground">
                Task ID:{' '}
                <span
                  className="font-mono text-white break-all cursor-pointer hover:text-blue-400"
                  title="Click to copy"
                  onClick={() => navigator.clipboard.writeText(publishedTask.id)}
                >
                  {publishedTask.id}
                </span>
              </p>
              <p className="text-muted-foreground">
                Type: <span className="text-white">{publishedTask.type}</span>
              </p>
              <p className="text-muted-foreground">
                Deadline: <span className="text-white">{deadlineCountdown || '—'}</span>
              </p>
              {publishedTask.scoring_dimensions?.length > 0 && (
                <div className="text-muted-foreground">
                  Dims: {publishedTask.scoring_dimensions.map((d, i) => (
                    <span key={i} className="inline-block mr-1 px-1 py-0.5 rounded bg-zinc-800 text-white text-[10px]">
                      {d.name}
                    </span>
                  ))}
                </div>
              )}
              {publishedTask.status === 'challenge_window' && (
                <p className="text-muted-foreground">
                  挑战期进行中
                </p>
              )}
              {publishedTask.payment_tx_hash && (
                <p className="text-muted-foreground">
                  Tx:{' '}
                  <a
                    href={`https://sepolia.basescan.org/tx/${publishedTask.payment_tx_hash}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-blue-400 hover:underline break-all"
                    title={publishedTask.payment_tx_hash}
                  >
                    {publishedTask.payment_tx_hash.slice(0, 10)}…{publishedTask.payment_tx_hash.slice(-6)}
                  </a>
                </p>
              )}
            </div>
          )}
        </form>
      </div>

      {/* Submit Result */}
      <div>
        <h2 className="text-base font-semibold mb-5">Submit Result</h2>

        {/* Current Task Info Bar */}
        {(publishedTask || taskId) && (
          <div className="mb-4 p-2.5 bg-zinc-900 border border-zinc-700 rounded text-xs space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground shrink-0">Task ID:</span>
              <span
                className="font-mono text-blue-300 break-all cursor-pointer hover:text-blue-200 flex-1"
                title="点击复制"
                onClick={() => navigator.clipboard.writeText(taskId)}
              >
                {taskId || '—'}
              </span>
            </div>
            {publishedTask && (
              <TaskStatusStepper type={publishedTask.type} status={publishedTask.status} />
            )}
          </div>
        )}

        <div className="flex flex-col gap-1.5 mb-4">
          <Label>Active Worker</Label>
          <Select
            value={String(activeWorkerIdx)}
            onValueChange={(v) => {
              const idx = parseInt(v, 10)
              setActiveWorkerIdx(idx)
              setWorkerId(workerIds[idx] || '')
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DEV_WORKERS.map((w, i) => (
                <SelectItem key={w.storageKey} value={String(i)}>
                  {w.nickname}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <WalletCard
          label={`${activeWorker?.nickname ?? 'Worker'} Wallet`}
          address={activeWorkerAddress}
          id={workerIds[activeWorkerIdx] || ''}
          balance={wrkBalances[activeWorkerIdx] || '...'}
          onRefresh={refreshWrkBalance}
          refreshing={wrkRefreshing}
        />

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Task ID</Label>
            <Input
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              required
              placeholder="Auto-filled after publish"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Content</Label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              rows={8}
              placeholder="Your submission content..."
            />
          </div>

          <Button type="submit" disabled={submitting}>
            {submitting ? (
              <span className="flex items-center gap-2">
                <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Submitting…
              </span>
            ) : 'Submit Result'}
          </Button>

          {submitError && (
            <p className="text-sm text-red-400 break-all">{submitError}</p>
          )}

          {/* Worker Status Board */}
          {Object.keys(workerSubs).length > 0 && (
            <div className="mt-2 border border-zinc-700 rounded overflow-hidden text-xs">
              <div className="px-3 py-1.5 bg-zinc-900 text-muted-foreground flex items-center gap-2">
                <span className="font-medium text-white">提交状态</span>
                {isPolling && (
                  <span className="inline-block w-2.5 h-2.5 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
                )}
              </div>
              <div className="divide-y divide-zinc-800">
                {DEV_WORKERS.map((w, i) => {
                  const sub = workerSubs[w.storageKey]
                  if (!sub) return null
                  return (
                    <WorkerSubRow
                      key={w.storageKey}
                      worker={w}
                      sub={sub}
                      isActive={i === activeWorkerIdx}
                      maxRevisions={polledTask?.max_revisions ?? publishedTask?.max_revisions ?? null}
                      onClick={() => {
                        setActiveWorkerIdx(i)
                        setWorkerId(workerIds[i] || '')
                      }}
                    />
                  )
                })}
              </div>
            </div>
          )}
        </form>

        {/* Challenge */}
        <div className="mt-8 pt-6 border-t border-zinc-700">
          <h2 className="text-base font-semibold mb-5">Submit Challenge</h2>
          <form onSubmit={handleChallenge} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>Task ID</Label>
              <Input
                value={challengeTaskId}
                onChange={(e) => setChallengeTaskId(e.target.value)}
                required
                placeholder="Task ID to challenge"
              />
            </div>

            <div className="p-3 bg-zinc-900 border border-zinc-700 rounded text-xs">
              <p className="text-muted-foreground">
                Submission:{' '}
                {challengeSubId ? (
                  <span className="font-mono text-white break-all">{challengeSubId}</span>
                ) : challengeTaskId ? (
                  <span className="text-yellow-400">No submission found for {activeWorker?.nickname ?? 'worker'} on this task</span>
                ) : (
                  <span className="text-muted-foreground">Enter a Task ID to auto-detect</span>
                )}
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>Reason</Label>
              <Textarea
                value={challengeReason}
                onChange={(e) => setChallengeReason(e.target.value)}
                required
                rows={3}
                placeholder="Why should the winner be reconsidered?"
              />
            </div>

            <Button type="submit" disabled={challenging || !challengeTaskId || !challengeSubId}>
              {challenging ? (
                <span className="flex items-center gap-2">
                  <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Challenging…
                </span>
              ) : 'Submit Challenge'}
            </Button>

            {challengeError && (
              <p className="text-sm text-red-400 break-all">{challengeError}</p>
            )}

            {challengeResult && (
              <div className="p-3 bg-zinc-900 border border-zinc-700 rounded text-xs space-y-1">
                <p className="text-green-400 font-medium">Challenge submitted</p>
                <p className="text-muted-foreground">
                  ID: <span className="font-mono text-white break-all">{challengeResult.id}</span>
                </p>
                <p className="text-muted-foreground">
                  Status: <span className="text-white">{challengeResult.status}</span>
                </p>
                {challengeResult.deposit_tx_hash && (
                  <p className="text-muted-foreground">
                    Deposit Tx:{' '}
                    <a
                      href={`https://sepolia.basescan.org/tx/${challengeResult.deposit_tx_hash}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-blue-400 hover:underline break-all"
                    >
                      {challengeResult.deposit_tx_hash.slice(0, 10)}…{challengeResult.deposit_tx_hash.slice(-6)}
                    </a>
                  </p>
                )}
                {challengeResult.challenger_wallet && (
                  <p className="text-muted-foreground">
                    Wallet: <span className="font-mono text-white break-all">{challengeResult.challenger_wallet}</span>
                  </p>
                )}
              </div>
            )}
          </form>
        </div>
      </div>

      {/* Arbiter Panel */}
      <ArbiterPanel />

      {/* Oracle Logs */}
      <OracleLogsPanel />

      {/* Activity History */}
      <BalanceTrustHistoryPanel />
    </div>
  )
}
