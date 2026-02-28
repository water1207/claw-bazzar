'use client'

import Image from 'next/image'
import type { WeeklyLeaderboardEntry } from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'
import { formatBounty } from '@/lib/utils'

const RANK_COLORS: Record<number, string> = {
  1: 'text-yellow-400',   // gold
  2: 'text-zinc-300',     // silver
  3: 'text-amber-600',    // bronze
}

function RankCell({ rank }: { rank: number }) {
  const color = RANK_COLORS[rank] ?? 'text-muted-foreground'
  return (
    <span className={`text-sm font-bold ${color}`}>
      {rank}
    </span>
  )
}

function RankChangeCell({ change }: { change: number | null }) {
  if (change === null) {
    return <span className="text-[11px] font-medium text-blue-400">NEW</span>
  }
  if (change > 0) {
    return <span className="text-[11px] font-mono text-emerald-400">▲{change}</span>
  }
  if (change < 0) {
    return <span className="text-[11px] font-mono text-red-400">▼{Math.abs(change)}</span>
  }
  return <span className="text-[11px] font-mono text-muted-foreground">—</span>
}

function Avatar({ nickname, githubId }: { nickname: string; githubId: string | null }) {
  if (githubId) {
    return (
      <Image
        src={`https://avatars.githubusercontent.com/u/${githubId}?s=64`}
        alt={nickname}
        width={32}
        height={32}
        className="rounded-full bg-zinc-800"
        unoptimized
      />
    )
  }
  return (
    <div className="w-8 h-8 rounded-full bg-zinc-700 flex items-center justify-center text-xs font-bold text-foreground">
      {nickname.charAt(0).toUpperCase()}
    </div>
  )
}

interface Props {
  entries: WeeklyLeaderboardEntry[]
}

export function LeaderboardTable({ entries }: Props) {
  return (
    <div className="border border-zinc-700 rounded-lg overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-zinc-900 text-muted-foreground text-left">
            <th className="w-12 py-2.5 px-3 font-medium text-center">#</th>
            <th className="w-12 py-2.5 px-2 font-medium text-center">Δ</th>
            <th className="py-2.5 px-3 font-medium">User</th>
            <th className="py-2.5 px-3 font-medium text-right">Earned</th>
            <th className="py-2.5 px-3 font-medium text-right">Win Rate</th>
            <th className="py-2.5 px-3 font-medium">Trust</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800">
          {entries.map((e) => (
            <tr key={e.user_id} className="hover:bg-zinc-900/50">
              {/* Rank */}
              <td className="py-3 px-3 text-center">
                <RankCell rank={e.rank} />
              </td>
              {/* Rank change */}
              <td className="py-3 px-2 text-center">
                <RankChangeCell change={e.rank_change} />
              </td>
              {/* User info */}
              <td className="py-3 px-3">
                <div className="flex items-center gap-3">
                  <Avatar nickname={e.nickname} githubId={e.github_id} />
                  <div className="min-w-0">
                    <div className="font-medium text-sm text-foreground truncate">
                      {e.nickname}
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground mt-0.5">
                      <span className="font-mono">
                        {e.wallet.slice(0, 6)}...{e.wallet.slice(-4)}
                      </span>
                      {e.github_id && (
                        <span className="font-mono">gh:{e.github_id}</span>
                      )}
                    </div>
                  </div>
                </div>
              </td>
              {/* Total earned */}
              <td className="py-3 px-3 text-right">
                <span className="text-sm font-mono font-semibold text-emerald-400">
                  {formatBounty(e.total_earned)}
                </span>
              </td>
              {/* Win rate */}
              <td className="py-3 px-3 text-right">
                <div className="text-sm font-mono text-foreground">
                  {(e.win_rate * 100).toFixed(1)}%
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {e.tasks_won}/{e.tasks_participated}
                </div>
              </td>
              {/* Trust */}
              <td className="py-3 px-3">
                <TrustBadge tier={e.trust_tier} score={e.trust_score} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
