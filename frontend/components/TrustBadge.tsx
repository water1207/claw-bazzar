import type { TrustTier } from '@/lib/api'

const tierConfig: Record<TrustTier, { bg: string; text: string }> = {
  S: { bg: 'bg-emerald-500/20', text: 'text-emerald-400' },
  A: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  B: { bg: 'bg-yellow-500/20', text: 'text-yellow-400' },
  C: { bg: 'bg-red-500/20', text: 'text-red-400' },
}

interface Props {
  tier: TrustTier
  score: number
}

export function TrustBadge({ tier, score }: Props) {
  const cfg = tierConfig[tier]
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium ${cfg.bg} ${cfg.text}`}>
      {tier} {Math.round(score)}
    </span>
  )
}
