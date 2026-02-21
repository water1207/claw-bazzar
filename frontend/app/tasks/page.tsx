'use client'

import { Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTasks, useTask } from '@/lib/api'
import { TaskTable } from '@/components/TaskTable'
import { TaskDetail } from '@/components/TaskDetail'

function TasksContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const selectedId = searchParams.get('id')

  const { data: tasks = [], isLoading } = useTasks()
  const { data: taskDetail, isLoading: detailLoading, error: detailError } = useTask(selectedId)

  function handleSelect(id: string) {
    router.push(`/tasks?id=${id}`, { scroll: false })
  }

  return (
    <div className="flex h-[calc(100vh-56px)] overflow-hidden">
      {/* Left panel: task list */}
      <div className="w-80 border-r border-border flex flex-col p-4 overflow-hidden shrink-0">
        <div className="flex items-center justify-between mb-3">
          <h1 className="font-semibold text-sm uppercase tracking-wide text-muted-foreground">
            Tasks
          </h1>
          {isLoading && (
            <span className="text-xs text-muted-foreground animate-pulse">
              Loading…
            </span>
          )}
        </div>
        <TaskTable
          tasks={tasks}
          selectedId={selectedId}
          onSelect={handleSelect}
        />
      </div>

      {/* Right panel: task detail */}
      <div className="flex-1 overflow-auto">
        {!selectedId ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            ← Select a task to view details
          </div>
        ) : detailLoading && !taskDetail ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm animate-pulse">
            Loading…
          </div>
        ) : detailError ? (
          <div className="flex items-center justify-center h-full text-red-400 text-sm">
            Task not found or failed to load
          </div>
        ) : taskDetail ? (
          <TaskDetail task={taskDetail} />
        ) : null}
      </div>
    </div>
  )
}

export default function TasksPage() {
  return (
    <Suspense>
      <TasksContent />
    </Suspense>
  )
}
