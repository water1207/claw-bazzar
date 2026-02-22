'use client'

import { useState, useMemo, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { createTask, createSubmission, registerUser } from '@/lib/api'
import type { UserRole } from '@/lib/api'
import { signX402Payment, getDevWalletAddress } from '@/lib/x402'
import { fetchUsdcBalance } from '@/lib/utils'
import type { Hex } from 'viem'

const DEV_PUBLISHER_WALLET_KEY = process.env.NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY as Hex | undefined
const DEV_WORKER_WALLET_KEY = process.env.NEXT_PUBLIC_DEV_WORKER_WALLET_KEY as Hex | undefined
const PLATFORM_WALLET = process.env.NEXT_PUBLIC_PLATFORM_WALLET as Hex | undefined

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
  const [threshold, setThreshold] = useState('')
  const [maxRevisions, setMaxRevisions] = useState('')
  const [deadline, setDeadline] = useState('')
  const [bounty, setBounty] = useState('')
  const [publishMsg, setPublishMsg] = useState<string | null>(null)

  // Submit form state
  const [taskId, setTaskId] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [content, setContent] = useState('')
  const [submitMsg, setSubmitMsg] = useState<string | null>(null)

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

  useEffect(() => {
    autoRegister().catch(console.error)
  }, [])

  useEffect(() => { refreshPubBalance() }, [publisherAddress])
  useEffect(() => { refreshWrkBalance() }, [workerAddress])

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

  async function handlePublish(e: React.FormEvent) {
    e.preventDefault()
    setPublishMsg(null)

    try {
      const bountyAmount = bounty ? parseFloat(bounty) : 0
      let paymentHeader: string | undefined
      if (bountyAmount > 0) {
        if (!DEV_PUBLISHER_WALLET_KEY || !PLATFORM_WALLET) {
          setPublishMsg('Error: DEV_PUBLISHER_WALLET_KEY or PLATFORM_WALLET env vars not set')
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
          deadline: new Date(deadline).toISOString(),
          publisher_id: publisherId || null,
          bounty: bountyAmount,
        },
        paymentHeader,
      )
      setPublishMsg(`Published: ${task.id}`)
      setTaskId(task.id)
      setTitle('')
      setDescription('')
      setThreshold('')
      setMaxRevisions('')
      setDeadline('')
      setBounty('')
    } catch (err) {
      setPublishMsg(`Error: ${(err as Error).message}`)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitMsg(null)
    try {
      const sub = await createSubmission(taskId, { worker_id: workerId, content })
      setSubmitMsg(`Submitted: revision ${sub.revision}, status: ${sub.status}`)
      setContent('')
    } catch (err) {
      setSubmitMsg(`Error: ${(err as Error).message}`)
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
            <Input
              type="datetime-local"
              required
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          </div>

          <Button type="submit" disabled={envError}>Publish</Button>

          {publishMsg && (
            <p className="text-sm font-mono break-all">{publishMsg}</p>
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

          <Button type="submit">Submit Result</Button>

          {submitMsg && (
            <p className="text-sm font-mono break-all">{submitMsg}</p>
          )}
        </form>
      </div>
    </div>
  )
}
