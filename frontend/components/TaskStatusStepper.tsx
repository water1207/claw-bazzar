import type { TaskStatus } from '@/lib/api'

const FASTEST_STEPS: { key: TaskStatus; label: string; desc: string }[] = [
  { key: 'open',   label: 'Open',   desc: '接受提交，Oracle 评分中' },
  { key: 'closed', label: 'Closed', desc: '已结算' },
]

const QUALITY_STEPS: { key: TaskStatus; label: string; desc: string }[] = [
  { key: 'open',             label: 'Open',      desc: '接受提交，Oracle 评分中' },
  { key: 'scoring',          label: 'Scoring',   desc: '批量横向对比中' },
  { key: 'challenge_window', label: 'Challenge', desc: '挑战窗口开放' },
  { key: 'arbitrating',      label: 'Arbitrate', desc: '陪审团仲裁中' },
  { key: 'closed',           label: 'Closed',    desc: '已结算' },
]

interface Props {
  type: 'fastest_first' | 'quality_first'
  status: TaskStatus
}

export function TaskStatusStepper({ type, status }: Props) {
  const steps = type === 'fastest_first' ? FASTEST_STEPS : QUALITY_STEPS
  const isVoided = status === 'voided'

  if (isVoided) {
    return (
      <div className="flex items-center gap-2 py-1">
        <span className="px-2 py-0.5 rounded bg-red-900/50 text-red-300 text-[11px] font-medium">VOIDED</span>
        <span className="text-xs text-muted-foreground">已作废（PW 恶意）</span>
      </div>
    )
  }

  const currentIdx = steps.findIndex((s) => s.key === status)

  return (
    <div className="flex items-start gap-0 mt-1.5">
      {steps.map((step, idx) => {
        const done = idx < currentIdx
        const active = idx === currentIdx
        const future = idx > currentIdx
        return (
          <div key={step.key} className="flex items-center">
            {/* Node */}
            <div className="flex flex-col items-center gap-0.5" title={step.desc}>
              <div
                className={[
                  'w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold border',
                  done   ? 'bg-green-700 border-green-600 text-green-100' : '',
                  active ? 'bg-blue-600 border-blue-500 text-white ring-2 ring-blue-400/40' : '',
                  future ? 'bg-zinc-800 border-zinc-700 text-zinc-500' : '',
                ].join(' ')}
              >
                {done ? '✓' : idx + 1}
              </div>
              <span
                className={[
                  'text-[9px] leading-tight text-center max-w-[44px]',
                  active ? 'text-blue-300 font-medium' : done ? 'text-green-400' : 'text-zinc-600',
                ].join(' ')}
              >
                {step.label}
              </span>
            </div>
            {/* Connector */}
            {idx < steps.length - 1 && (
              <div
                className={[
                  'h-px w-6 mb-[10px]',
                  done ? 'bg-green-700' : 'bg-zinc-700',
                ].join(' ')}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
