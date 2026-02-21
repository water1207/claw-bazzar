import { Badge } from '@/components/ui/badge'

interface Props {
  status: 'open' | 'closed'
}

export function StatusBadge({ status }: Props) {
  return (
    <Badge variant={status === 'open' ? 'default' : 'destructive'}>
      {status === 'open' ? '🟢 open' : '🔴 closed'}
    </Badge>
  )
}
