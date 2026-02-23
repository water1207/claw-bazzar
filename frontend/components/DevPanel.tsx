'use client'

import { useState, useMemo, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { createTask, createSubmission, registerUser, createChallenge } from '@/lib/api'
import type { UserRole, Task, Submission, TaskDetail, Challenge } from '@/lib/api'
import { signX402Payment, getDevWalletAddress } from '@/lib/x402'
import { fetchUsdcBalance } from '@/lib/utils'
import type { Hex } from 'viem'

const DEV_PUBLISHER_WALLET_KEY = process.env.NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY as Hex | undefined
const DEV_WORKER_WALLET_KEY = process.env.NEXT_PUBLIC_DEV_WORKER_WALLET_KEY as Hex | undefined
const PLATFORM_WALLET = process.env.NEXT_PUBLIC_PLATFORM_WALLET as Hex | undefined

const PRESETS = [
  { label: '1h', value: '1', unit: 'hours' },
  { label: '6h', value: '6', unit: 'hours' },
  { label: '12h', value: '12', unit: 'hours' },
  { label: '1d', value: '1', unit: 'days' },
  { label: '3d', value: '3', unit: 'days' },
  { label: '7d', value: '7', unit: 'days' },
] as const

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
        <p className="text-xs text-muted-foreground mt-0.5">
          ID: <span className="font-mono text-white break-all">{id}</span>
        </p>
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

export function DevPanel() {
  const publisherAddress = useMemo(() => {
    if (!DEV_PUBLISHER_WALLET_KEY) return null
    try { return getDevWalletAddress(DEV_PUBLISHER_WALLET_KEY) } catch { return null }
  }, [])

  const workerAddress = useMemo(() => {
    if (!DEV_WORKER_WALLET_KEY) return null
    try { return getDevWalletAddress(DEV_WORKER_WALLET_KEY) } catch { return null }
  }, [])

  const envError = !DEV_PUBLISHER_WALLET_KEY || !PLATFORM_WALLET

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
  const [deadlineDuration, setDeadlineDuration] = useState('1')
  const [deadlineUnit, setDeadlineUnit] = useState<'hours' | 'days'>('days')
  const [bounty, setBounty] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [publishedTask, setPublishedTask] = useState<Task | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)

  // Submit form state
  const [taskId, setTaskId] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [content, setContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [trackedSub, setTrackedSub] = useState<Submission | null>(null)
  const [polledSub, setPolledSub] = useState<Submission | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Challenge form state
  const [challengeTaskId, setChallengeTaskId] = useState('')
  const [challengeSubId, setChallengeSubId] = useState('')
  const [challengeReason, setChallengeReason] = useState('')
  const [challenging, setChallenging] = useState(false)
  const [challengeResult, setChallengeResult] = useState<Challenge | null>(null)
  const [challengeError, setChallengeError] = useState<string | null>(null)

  // Balance state
  const [pubBalance, setPubBalance] = useState('...')
  const [wrkBalance, setWrkBalance] = useState('...')
  const [pubRefreshing, setPubRefreshing] = useState(false)
  const [wrkRefreshing, setWrkRefreshing] = useState(false)

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
    if (!workerAddress) return
    setWrkRefreshing(true)
    try {
      setWrkBalance(await fetchUsdcBalance(workerAddress))
    } catch {
      setWrkBalance('error')
    } finally {
      setWrkRefreshing(false)
    }
  }

  async function autoRegister() {
    // Publisher
    let pubId = localStorage.getItem('devPublisherId')
    if (!pubId && DEV_PUBLISHER_WALLET_KEY) {
      const user = await registerUser({
        nickname: 'dev-publisher',
        wallet: publisherAddress!,
        role: 'publisher',
      })
      pubId = user.id
      localStorage.setItem('devPublisherId', pubId)
    }
    if (pubId) setPublisherId(pubId)

    // Worker
    let wrkId = localStorage.getItem('devWorkerId')
    if (!wrkId && DEV_WORKER_WALLET_KEY) {
      const user = await registerUser({
        nickname: 'dev-worker',
        wallet: workerAddress!,
        role: 'worker',
      })
      wrkId = user.id
      localStorage.setItem('devWorkerId', wrkId)
    }
    if (wrkId) setWorkerId(wrkId)
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { autoRegister().catch(console.error) }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshPubBalance() }, [publisherAddress])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshWrkBalance() }, [workerAddress])

  // Poll submission status after submit
  useEffect(() => {
    if (!trackedSub) return
    if (polledSub?.status === 'scored') return

    pollRef.current = setInterval(async () => {
      try {
        const resp = await fetch(`/api/tasks/${trackedSub.task_id}`)
        if (!resp.ok) return
        const task: TaskDetail = await resp.json()
        const found = task.submissions.find((s) => s.id === trackedSub.id)
        if (found) {
          setPolledSub(found)
          if (found.status === 'scored') {
            clearInterval(pollRef.current!)
            pollRef.current = null
          }
        }
      } catch {}
    }, 2000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackedSub])

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
    const ms = n * (deadlineUnit === 'days' ? 86_400_000 : 3_600_000)
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
        if (!DEV_PUBLISHER_WALLET_KEY || !PLATFORM_WALLET) {
          setPublishError('Error: DEV_PUBLISHER_WALLET_KEY or PLATFORM_WALLET env vars not set')
          return
        }
        paymentHeader = await signX402Payment({
          privateKey: DEV_PUBLISHER_WALLET_KEY,
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
        },
        paymentHeader,
      )
      setPublishedTask(task)
      setTaskId(task.id)
      setTitle('')
      setDescription('')
      setThreshold('0.8')
      setMaxRevisions('')
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
    setTrackedSub(null)
    setPolledSub(null)
    if (pollRef.current) clearInterval(pollRef.current)
    setSubmitting(true)
    try {
      const sub = await createSubmission(taskId, { worker_id: workerId, content })
      setTrackedSub(sub)
      setPolledSub(sub)
      setContent('')
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
      const result = await createChallenge(challengeTaskId, {
        challenger_submission_id: challengeSubId,
        reason: challengeReason,
      })
      setChallengeResult(result)
      setChallengeReason('')
    } catch (err) {
      setChallengeError((err as Error).message)
    } finally {
      setChallenging(false)
    }
  }

  return (
    <div className="grid grid-cols-3 gap-10 p-8 max-w-6xl">
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
                ID: <span className="font-mono text-white break-all">{publishedTask.id}</span>
              </p>
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

        <WalletCard
          label="Worker Wallet"
          address={workerAddress}
          id={workerId}
          balance={wrkBalance}
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
            <Label>Worker ID</Label>
            <Input
              value={workerId}
              onChange={(e) => setWorkerId(e.target.value)}
              required
              placeholder="Auto-filled after register"
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

          {polledSub && (
            <div className="p-3 bg-zinc-900 border border-zinc-700 rounded text-xs space-y-1">
              <div className="flex items-center gap-2">
                {polledSub.status === 'pending' ? (
                  <>
                    <span className="inline-block w-3 h-3 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
                    <span className="text-yellow-400 font-medium">Scoring…</span>
                  </>
                ) : (
                  <span className="text-green-400 font-medium">Scored</span>
                )}
              </div>
              <p className="text-muted-foreground">
                Revision: <span className="text-white">{polledSub.revision}</span>
              </p>
              <p className="text-muted-foreground">
                ID: <span className="font-mono text-white break-all">{polledSub.id}</span>
              </p>
              {polledSub.score !== null && (
                <p className="text-muted-foreground">
                  Score: <span className="text-white font-mono">{polledSub.score.toFixed(2)}</span>
                </p>
              )}
              {polledSub.oracle_feedback && (
                <p className="text-muted-foreground">
                  Feedback: <span className="text-white">{polledSub.oracle_feedback}</span>
                </p>
              )}
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
                placeholder="Task in challenge_window state"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>Your Submission ID</Label>
              <Input
                value={challengeSubId}
                onChange={(e) => setChallengeSubId(e.target.value)}
                required
                placeholder="Your (non-winner) submission ID"
              />
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

            <Button type="submit" disabled={challenging}>
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
              </div>
            )}
          </form>
        </div>
      </div>
    </div>
  )
}
