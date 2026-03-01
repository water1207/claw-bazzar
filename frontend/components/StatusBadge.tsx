import { Badge } from '@/components/ui/badge'
import type { TaskStatus } from '@/lib/api'

const STATUS_CONFIG: Record<TaskStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; label: string }> = {
  open:             { variant: 'default',     label: 'open' },
  scoring:          { variant: 'secondary',   label: 'scoring' },
  challenge_window: { variant: 'outline',     label: 'challenge' },
  arbitrating:      { variant: 'secondary',   label: 'arbitrating' },
  closed:           { variant: 'destructive', label: 'closed' },
  voided:           { variant: 'destructive', label: 'voided' },
}

interface Props {
  status: TaskStatus
}

export function StatusBadge({ status }: Props) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.open
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>
}
