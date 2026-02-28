'use client'

import { useState } from 'react'
import { useUser, useTrustProfile, useUserStats, useBalanceEvents, useTrustEvents } from '@/lib/api'
import { TrustBadge } from './TrustBadge'
import { BalanceEventsTable, TrustEventsTable } from './BalanceTrustHistoryPanel'
import { formatBounty } from '@/lib/utils'

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-3">
      <div className="text-[11px] text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
      <div className="text-base font-mono font-semibold text-foreground">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  )
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

interface Props {
  userId: string
}

type Tab = 'balance' | 'trust'

export function ProfileView({ userId }: Props) {
  const { data: user } = useUser(userId)
  const { data: trust } = useTrustProfile(userId)
  const { data: stats } = useUserStats(userId)
  const { data: balanceEvents = [] } = useBalanceEvents(userId)
  const { data: trustEvents = [] } = useTrustEvents(userId)
  const [tab, setTab] = useState<Tab>('balance')

  if (!user) {
    return (
      <div className="text-center text-muted-foreground text-sm py-12">
        Loading...
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold">{user.nickname}</h2>
            {trust && <TrustBadge tier={trust.trust_tier} score={trust.trust_score} />}
            {trust?.is_arbiter && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-500/20 text-purple-400">
                Arbiter
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-1 flex gap-4">
            <span>Role: {user.role}</span>
            {stats && <span>Joined {formatDate(stats.registered_at)}</span>}
            <span className="font-mono" title={user.wallet}>
              {user.wallet.slice(0, 6)}...{user.wallet.slice(-4)}
            </span>
          </div>
        </div>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard
            label="Tasks Participated"
            value={String(stats.tasks_participated)}
          />
          <StatCard
            label="Tasks Won"
            value={String(stats.tasks_won)}
            sub={`Win rate: ${(stats.win_rate * 100).toFixed(1)}%`}
          />
          <StatCard
            label="Total Earned"
            value={formatBounty(stats.total_earned)}
          />
          <StatCard
            label="Submissions (30d)"
            value={String(stats.submissions_last_30d)}
          />
          {stats.malicious_count > 0 && (
            <StatCard
              label="Malicious"
              value={String(stats.malicious_count)}
              sub="policy violations"
            />
          )}
          {trust && trust.staked_amount > 0 && (
            <StatCard
              label="Staked"
              value={formatBounty(trust.staked_amount)}
              sub={`Bonus: +${trust.stake_bonus.toFixed(1)}`}
            />
          )}
        </div>
      )}

      {/* Activity History */}
      <div>
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-3">
          Activity History
          <span className="ml-2 text-[10px] font-normal normal-case">
            {balanceEvents.length} balance / {trustEvents.length} trust
          </span>
        </h3>
        <div className="flex gap-1 mb-3">
          <button
            type="button"
            onClick={() => setTab('balance')}
            className={[
              'px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
              tab === 'balance'
                ? 'bg-accent text-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            ].join(' ')}
          >
            Balance Events
          </button>
          <button
            type="button"
            onClick={() => setTab('trust')}
            className={[
              'px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
              tab === 'trust'
                ? 'bg-accent text-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            ].join(' ')}
          >
            Trust Events
          </button>
        </div>
        <div className="border border-zinc-700 rounded-lg overflow-hidden">
          {tab === 'balance' && <BalanceEventsTable events={balanceEvents} />}
          {tab === 'trust' && <TrustEventsTable events={trustEvents} />}
        </div>
      </div>
    </div>
  )
}
