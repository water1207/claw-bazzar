import { Badge } from '@/components/ui/badge'
import type { PayoutStatus } from '@/lib/api'

const config: Record<PayoutStatus, { variant: 'secondary' | 'default' | 'destructive'; label: string }> = {
  pending: { variant: 'secondary', label: 'pending' },
  paid: { variant: 'default', label: 'paid' },
  failed: { variant: 'destructive', label: 'failed' },
  refunded: { variant: 'secondary', label: 'refunded' },
}

interface Props {
  status: PayoutStatus
}

export function PayoutBadge({ status }: Props) {
  const { variant, label } = config[status]
  return <Badge variant={variant}>{label}</Badge>
}
