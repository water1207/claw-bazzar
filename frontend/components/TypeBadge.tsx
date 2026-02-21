import { Badge } from '@/components/ui/badge'

interface Props {
  type: 'fastest_first' | 'quality_first'
}

export function TypeBadge({ type }: Props) {
  return (
    <Badge variant="outline" className="font-mono text-xs">
      {type === 'fastest_first' ? 'fastest' : 'quality'}
    </Badge>
  )
}
