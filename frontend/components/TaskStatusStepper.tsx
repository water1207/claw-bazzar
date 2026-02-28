import type { TaskStatus } from '@/lib/api'

type TabHint = 'submissions' | 'challenges' | null

interface Step {
  key: TaskStatus
  label: string
  tabHint: TabHint
}

const FASTEST_STEPS: Step[] = [
  { key: 'open',   label: 'Open',   tabHint: 'submissions' },
  { key: 'closed', label: 'Closed', tabHint: null },
]

const QUALITY_STEPS: Step[] = [
  { key: 'open',             label: 'Open',      tabHint: 'submissions' },
  { key: 'scoring',          label: 'Scoring',   tabHint: 'submissions' },
  { key: 'challenge_window', label: 'Challenge', tabHint: 'challenges' },
  { key: 'arbitrating',      label: 'Arbiter',   tabHint: 'challenges' },
  { key: 'closed',           label: 'Closed',    tabHint: null },
]

interface Props {
  type: 'fastest_first' | 'quality_first'
  status: TaskStatus
  onTabHint?: (tab: TabHint) => void
}

export function TaskStatusStepper({ type, status, onTabHint }: Props) {
  const steps = type === 'fastest_first' ? FASTEST_STEPS : QUALITY_STEPS
  const isVoided = status === 'voided'

  if (isVoided) {
    return (
      <div className="flex items-center gap-2 py-1">
        <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-red-950 text-red-300 border border-red-800">
          VOIDED
        </span>
        <span className="text-xs text-muted-foreground">已作废（PW 恶意）</span>
      </div>
    )
  }

  const currentIdx = steps.findIndex((s) => s.key === status)

  return (
    <div className="flex items-center gap-0 mt-2">
      {steps.map((step, idx) => {
        const done   = idx < currentIdx
        const active = idx === currentIdx
        const future = idx > currentIdx
        const clickable = onTabHint && step.tabHint !== null

        return (
          <div key={step.key} className="flex items-center">
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onTabHint?.(step.tabHint)}
              title={step.tabHint ? `查看 ${step.tabHint}` : undefined}
              className={[
                'px-2.5 py-0.5 rounded-full text-[11px] font-medium border transition-colors',
                done
                  ? 'bg-emerald-950 text-emerald-400 border-emerald-800'
                  : '',
                active
                  ? 'bg-blue-600 text-white border-blue-500 shadow-[0_0_0_2px_rgba(96,165,250,0.25)]'
                  : '',
                future
                  ? 'bg-transparent text-zinc-600 border-zinc-700'
                  : '',
                clickable
                  ? 'cursor-pointer hover:brightness-125'
                  : 'cursor-default',
              ].join(' ')}
            >
              {done ? `✓ ${step.label}` : step.label}
            </button>

            {idx < steps.length - 1 && (
              <div
                className={[
                  'h-px w-4 shrink-0',
                  done ? 'bg-emerald-800' : 'bg-zinc-700',
                ].join(' ')}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
