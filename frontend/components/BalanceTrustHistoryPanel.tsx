'use client'

import { useState, useEffect } from 'react'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useBalanceEvents, useTrustEvents } from '@/lib/api'
import type { BalanceEvent, TrustEvent } from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'
import type { TrustTier } from '@/lib/api'
import { ALL_DEV_USERS } from '@/lib/dev-wallets'

const EVENT_LABELS: Record<string, { label: string; color: string }> = {
  bounty_paid: { label: 'Bounty Paid', color: 'bg-orange-500/20 text-orange-300' },
  payout_received: { label: 'Payout', color: 'bg-emerald-500/20 text-emerald-300' },
  refund_received: { label: 'Refund', color: 'bg-blue-500/20 text-blue-300' },
  challenge_deposit_paid: { label: 'Challenge Deposit', color: 'bg-yellow-500/20 text-yellow-300' },
  arbiter_reward: { label: 'Arbiter Reward', color: 'bg-purple-500/20 text-purple-300' },
  stake_deposited: { label: 'Stake', color: 'bg-zinc-500/20 text-zinc-300' },
  stake_slashed: { label: 'Slashed', color: 'bg-red-500/20 text-red-300' },
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function AmountCell({ amount, direction }: { amount: number; direction: string }) {
  const isIn = direction === 'inflow'
  return (
    <span className={`font-mono text-xs ${isIn ? 'text-emerald-400' : 'text-red-400'}`}>
      {isIn ? '+' : '-'}{amount.toFixed(2)}
    </span>
  )
}

function BalanceEventsTable({ events }: { events: BalanceEvent[] }) {
  if (events.length === 0) {
    return <p className="text-xs text-muted-foreground py-6 text-center">No balance events</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-700 text-left text-muted-foreground">
            <th className="py-2 px-2 font-medium">Time</th>
            <th className="py-2 px-2 font-medium">Type</th>
            <th className="py-2 px-2 font-medium">Role</th>
            <th className="py-2 px-2 font-medium text-right">Amount</th>
            <th className="py-2 px-2 font-medium">Task</th>
            <th className="py-2 px-2 font-medium">Tx</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800">
          {events.map((e) => {
            const meta = EVENT_LABELS[e.event_type] || { label: e.event_type, color: 'bg-zinc-700 text-zinc-300' }
            return (
              <tr key={e.id} className="hover:bg-zinc-900/50">
                <td className="py-1.5 px-2 text-muted-foreground whitespace-nowrap">{formatTime(e.created_at)}</td>
                <td className="py-1.5 px-2">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${meta.color}`}>{meta.label}</span>
                </td>
                <td className="py-1.5 px-2 text-muted-foreground">{e.role}</td>
                <td className="py-1.5 px-2 text-right">
                  <AmountCell amount={e.amount} direction={e.direction} />
                </td>
                <td className="py-1.5 px-2 text-white truncate max-w-[200px]" title={e.task_title || ''}>
                  {e.task_title || '—'}
                </td>
                <td className="py-1.5 px-2">
                  {e.tx_hash ? (
                    <a
                      href={`https://sepolia.basescan.org/tx/${e.tx_hash}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-400 hover:underline font-mono"
                      title={e.tx_hash}
                    >
                      {e.tx_hash.slice(0, 10)}...
                    </a>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const TRUST_EVENT_LABELS: Record<string, string> = {
  task_completed: 'Task Won',
  task_failed: 'Task Failed',
  publisher_completed: 'Published',
  challenge_upheld_challenger: 'Challenge Won',
  challenge_rejected_challenger: 'Challenge Lost',
  challenge_upheld_winner: 'Challenged (Lost)',
  challenge_rejected_winner: 'Defended',
  challenge_malicious_challenger: 'Malicious Challenge',
  arbiter_majority: 'Arbiter Majority',
  arbiter_minority: 'Arbiter Minority',
  consolation: 'Consolation',
  stake_bonus: 'Stake Bonus',
}

function TrustEventsTable({ events }: { events: TrustEvent[] }) {
  if (events.length === 0) {
    return <p className="text-xs text-muted-foreground py-6 text-center">No trust events</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-700 text-left text-muted-foreground">
            <th className="py-2 px-2 font-medium">Time</th>
            <th className="py-2 px-2 font-medium">Event</th>
            <th className="py-2 px-2 font-medium text-right">Delta</th>
            <th className="py-2 px-2 font-medium">Score</th>
            <th className="py-2 px-2 font-medium">Task</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800">
          {events.map((e) => {
            const isPositive = e.delta >= 0
            return (
              <tr key={e.id} className="hover:bg-zinc-900/50">
                <td className="py-1.5 px-2 text-muted-foreground whitespace-nowrap">{formatTime(e.created_at)}</td>
                <td className="py-1.5 px-2">
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-zinc-800 text-zinc-200">
                    {TRUST_EVENT_LABELS[e.event_type] || e.event_type}
                  </span>
                </td>
                <td className="py-1.5 px-2 text-right">
                  <span className={`font-mono ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                    {isPositive ? '+' : ''}{e.delta.toFixed(1)}
                  </span>
                </td>
                <td className="py-1.5 px-2 font-mono text-muted-foreground">
                  {e.score_before.toFixed(0)} → {e.score_after.toFixed(0)}
                </td>
                <td className="py-1.5 px-2">
                  {e.task_id ? (
                    <span className="font-mono text-muted-foreground" title={e.task_id}>
                      {e.task_id.slice(0, 8)}...
                    </span>
                  ) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function BalanceTrustHistoryPanel() {
  const [collapsed, setCollapsed] = useState(false)
  const [selectedKey, setSelectedKey] = useState<string>('')
  const [userId, setUserId] = useState<string | null>(null)

  // Resolve available users from localStorage
  const [available, setAvailable] = useState<{ label: string; key: string; id: string }[]>([])
  useEffect(() => {
    const found: { label: string; key: string; id: string }[] = []
    for (const sk of ALL_DEV_USERS) {
      const id = localStorage.getItem(sk.key)
      if (id) found.push({ ...sk, id })
    }
    setAvailable(found)
    if (found.length > 0 && !selectedKey) {
      setSelectedKey(found[0].key)
      setUserId(found[0].id)
    }
  }, [])

  function onUserChange(key: string) {
    setSelectedKey(key)
    const entry = available.find(a => a.key === key)
    setUserId(entry?.id || null)
  }

  const { data: balanceEvents = [] } = useBalanceEvents(userId)
  const { data: trustEvents = [] } = useTrustEvents(userId)

  return (
    <div className="col-span-4 mt-6 border-t border-zinc-700 pt-6">
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center gap-2 text-base font-semibold hover:text-blue-400"
        >
          <span className="text-xs">{collapsed ? '\u25b6' : '\u25bc'}</span>
          Activity History
        </button>
        <span className="text-xs text-muted-foreground">
          {balanceEvents.length} balance · {trustEvents.length} trust
        </span>
        {!collapsed && available.length > 0 && (
          <Select value={selectedKey} onValueChange={onUserChange}>
            <SelectTrigger className="w-[160px] h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {available.map((a) => (
                <SelectItem key={a.key} value={a.key}>{a.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {!collapsed && (
        <Tabs defaultValue="balance" className="w-full">
          <TabsList className="mb-3">
            <TabsTrigger value="balance" className="text-xs">Balance Events</TabsTrigger>
            <TabsTrigger value="trust" className="text-xs">Trust Events</TabsTrigger>
          </TabsList>
          <TabsContent value="balance">
            <BalanceEventsTable events={balanceEvents} />
          </TabsContent>
          <TabsContent value="trust">
            <TrustEventsTable events={trustEvents} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
