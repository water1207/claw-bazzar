'use client'

import { useMemo, useState } from 'react'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Task } from '@/lib/api'
import { formatDeadline, formatBounty } from '@/lib/utils'
import { StatusBadge } from './StatusBadge'
import { TypeBadge } from './TypeBadge'

interface Props {
  tasks: Task[]
  selectedId: string | null
  onSelect: (id: string) => void
}

export function TaskTable({ tasks, selectedId, onSelect }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const filtered = useMemo(() => {
    return tasks
      .filter((t) => statusFilter === 'all' || t.status === statusFilter)
      .filter((t) => typeFilter === 'all' || t.type === typeFilter)
      .toSorted((a, b) => {
        const diff = new Date(a.deadline).getTime() - new Date(b.deadline).getTime()
        return sortDir === 'asc' ? diff : -diff
      })
  }, [tasks, statusFilter, typeFilter, sortDir])

  return (
    <div className="flex flex-col gap-3 h-full overflow-hidden">
      {/* Filter bar */}
      <div className="flex gap-2 items-center">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-7 text-xs flex-1 min-w-0">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="scoring">Scoring</SelectItem>
            <SelectItem value="challenge_window">Challenge</SelectItem>
            <SelectItem value="arbitrating">Arbitrating</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
            <SelectItem value="voided">Voided</SelectItem>
          </SelectContent>
        </Select>

        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="h-7 text-xs flex-1 min-w-0">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="fastest_first">Fastest</SelectItem>
            <SelectItem value="quality_first">Quality</SelectItem>
          </SelectContent>
        </Select>

        <button
          className="text-xs text-muted-foreground hover:text-foreground shrink-0 tabular-nums"
          onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
        >
          DDL {sortDir === 'asc' ? '↑' : '↓'}
        </button>
      </div>

      {/* Task card list */}
      <div className="overflow-auto flex-1 space-y-1.5 pr-0.5">
        {filtered.map((task) => {
          const { label, expired } = formatDeadline(task.deadline)
          const isSelected = selectedId === task.id
          return (
            <div
              key={task.id}
              onClick={() => onSelect(task.id)}
              className={[
                'p-3 rounded-lg border cursor-pointer transition-colors select-none',
                isSelected
                  ? 'bg-accent border-accent-foreground/20'
                  : 'border-border hover:bg-muted/40',
              ].join(' ')}
            >
              {/* Row 1: Title + Bounty */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <span className="font-medium text-sm leading-snug line-clamp-2 flex-1">
                  {task.title}
                </span>
                {task.bounty !== null && task.bounty > 0 && (
                  <span className="font-mono text-sm text-green-400 shrink-0 tabular-nums">
                    {formatBounty(task.bounty)}
                  </span>
                )}
              </div>
              {/* Row 2: Type + Status + Deadline */}
              <div className="flex items-center gap-1.5">
                <TypeBadge type={task.type} />
                <StatusBadge status={task.status} />
                <span
                  className={[
                    'ml-auto text-[11px] tabular-nums',
                    expired ? 'text-red-400' : 'text-muted-foreground',
                  ].join(' ')}
                >
                  {label}
                </span>
              </div>
            </div>
          )
        })}
        {filtered.length === 0 && (
          <div className="text-center text-muted-foreground text-sm py-12">
            No tasks found
          </div>
        )}
      </div>
    </div>
  )
}
