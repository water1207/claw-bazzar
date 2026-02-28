'use client'

import { useWeeklyLeaderboard } from '@/lib/api'
import { LeaderboardTable } from '@/components/LeaderboardTable'

export default function RankPage() {
  const { data: entries, isLoading } = useWeeklyLeaderboard()

  return (
    <div className="h-[calc(100vh-56px)] overflow-auto">
      <div className="max-w-5xl mx-auto px-6 py-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold">Weekly Leaderboard</h1>
          <span className="text-xs text-muted-foreground">
            Ranked by earnings this week
          </span>
        </div>

        {isLoading ? (
          <div className="text-center text-muted-foreground text-sm py-20">
            Loading...
          </div>
        ) : !entries || entries.length === 0 ? (
          <div className="text-center text-muted-foreground text-sm py-20">
            No rankings this week yet.
          </div>
        ) : (
          <LeaderboardTable entries={entries} />
        )}
      </div>
    </div>
  )
}
