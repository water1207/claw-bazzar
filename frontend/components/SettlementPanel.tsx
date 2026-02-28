'use client'

import { useSettlement } from '@/lib/api'
import type { Task, SettlementDistribution } from '@/lib/api'
import { SettlementSankey } from './SettlementSankey'
import { formatBounty } from '@/lib/utils'

const BASE_SEPOLIA_EXPLORER = 'https://sepolia.basescan.org/tx'

function TxLink({ hash }: { hash: string }) {
  const short = `${hash.slice(0, 10)}...${hash.slice(-6)}`
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

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-3">
      <div className="text-[11px] text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
      <div className="text-base font-mono font-semibold text-foreground">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  )
}

const TYPE_BADGES: Record<SettlementDistribution['type'], { bg: string; text: string; label: string }> = {
  winner:           { bg: 'bg-emerald-900/40', text: 'text-emerald-400', label: 'Winner' },
  refund:           { bg: 'bg-blue-900/40',    text: 'text-blue-400',    label: 'Refund' },
  arbiter:          { bg: 'bg-purple-900/40',  text: 'text-purple-400',  label: 'Arbiter' },
  platform:         { bg: 'bg-zinc-800',       text: 'text-zinc-400',    label: 'Platform' },
  publisher_refund: { bg: 'bg-blue-900/40',    text: 'text-blue-400',    label: 'Pub Refund' },
}

interface Props {
  task: Task
}

export function SettlementPanel({ task }: Props) {
  const { data, isLoading, error } = useSettlement(task.id)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
        Loading settlement data...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
        Settlement data not available.
      </div>
    )
  }

  const { summary, sources, distributions, resolve_tx_hash, escrow_total } = data

  return (
    <div className="flex flex-col gap-5">
      {/* Summary stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Winner Payout"
          value={formatBounty(summary.winner_payout)}
          sub={summary.winner_nickname
            ? `${summary.winner_nickname} (Tier ${summary.winner_tier ?? 'A'} / ${(summary.payout_rate * 100).toFixed(0)}%)`
            : undefined}
        />
        <StatCard
          label="Arbiter Reward"
          value={formatBounty(summary.arbiter_reward_total)}
        />
        <StatCard
          label="Platform Fee"
          value={formatBounty(summary.platform_fee)}
        />
        <StatCard
          label="Deposits"
          value={`+${formatBounty(summary.deposits_refunded)} / -${formatBounty(summary.deposits_forfeited)}`}
          sub="refunded / forfeited"
        />
      </div>

      {/* Sankey diagram */}
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-4">
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-3">
          Fund Flow
        </h3>
        <SettlementSankey
          sources={sources}
          distributions={distributions}
          escrowTotal={escrow_total}
        />
      </div>

      {/* Distribution detail table */}
      <div>
        <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest mb-2.5">
          Distribution Details
        </h3>
        <div className="border border-zinc-700 rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-zinc-900 text-muted-foreground text-left">
                <th className="px-3 py-2 font-medium">#</th>
                <th className="px-3 py-2 font-medium">Recipient</th>
                <th className="px-3 py-2 font-medium text-right">Amount</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Wallet</th>
              </tr>
            </thead>
            <tbody>
              {distributions.map((d, i) => {
                const badge = TYPE_BADGES[d.type] ?? TYPE_BADGES.platform
                return (
                  <tr key={i} className="border-t border-zinc-800 hover:bg-zinc-900/50">
                    <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                    <td className="px-3 py-2 font-medium">{d.label}</td>
                    <td className="px-3 py-2 text-right font-mono">{formatBounty(d.amount)}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${badge.bg} ${badge.text}`}>
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-muted-foreground">
                      {d.wallet ? `${d.wallet.slice(0, 6)}...${d.wallet.slice(-4)}` : '--'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-zinc-700 bg-zinc-900">
                <td className="px-3 py-2" colSpan={2}>
                  <span className="font-medium text-muted-foreground">Total Escrow</span>
                </td>
                <td className="px-3 py-2 text-right font-mono font-semibold">{formatBounty(escrow_total)}</td>
                <td className="px-3 py-2" colSpan={2}>
                  {resolve_tx_hash && (
                    <span className="flex items-center gap-1.5">
                      <span className="text-muted-foreground">Tx:</span>
                      <TxLink hash={resolve_tx_hash} />
                    </span>
                  )}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  )
}
