'use client'

import { useMemo, useState } from 'react'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Task } from '@/lib/api'
import { formatDeadline } from '@/lib/utils'
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
      .sort((a, b) => {
        const diff = new Date(a.deadline).getTime() - new Date(b.deadline).getTime()
        return sortDir === 'asc' ? diff : -diff
      })
  }, [tasks, statusFilter, typeFilter, sortDir])

  return (
    <div className="flex flex-col gap-3 h-full overflow-hidden">
      {/* Filter controls */}
      <div className="flex gap-2 flex-wrap">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-28 h-8 text-xs">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
          </SelectContent>
        </Select>

        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-28 h-8 text-xs">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="fastest_first">Fastest</SelectItem>
            <SelectItem value="quality_first">Quality</SelectItem>
          </SelectContent>
        </Select>

        <button
          className="text-xs text-muted-foreground hover:text-foreground ml-auto"
          onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
        >
          Deadline {sortDir === 'asc' ? '↑' : '↓'}
        </button>
      </div>

      {/* Task list */}
      <div className="overflow-auto flex-1">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>⏱</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((task) => {
              const { label, expired } = formatDeadline(task.deadline)
              const isSelected = selectedId === task.id
              return (
                <TableRow
                  key={task.id}
                  className={`cursor-pointer ${
                    isSelected ? 'bg-accent' : 'hover:bg-muted/50'
                  }`}
                  onClick={() => onSelect(task.id)}
                >
                  <TableCell className="font-medium max-w-[120px] truncate">
                    {task.title}
                  </TableCell>
                  <TableCell>
                    <TypeBadge type={task.type} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={task.status} />
                  </TableCell>
                  <TableCell
                    className={`text-xs ${
                      expired ? 'text-red-400' : 'text-muted-foreground'
                    }`}
                  >
                    {label}
                  </TableCell>
                </TableRow>
              )
            })}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-10">
                  No tasks found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
