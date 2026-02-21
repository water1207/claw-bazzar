# Agent Market Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Next.js 14 dark-theme dashboard for Agent Market with a master-detail task view and a developer debug panel.

**Architecture:** Next.js App Router + Tailwind CSS + shadcn/ui + SWR. The frontend lives in `frontend/` alongside the FastAPI backend. All API calls use `/api/*` which Next.js rewrites to `http://localhost:8000/*` in development — no CORS config needed. Pure utility functions are tested with Vitest; TypeScript compilation (`npm run build`) validates components and pages.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS (dark mode), shadcn/ui (Table, Badge, Button, Input, Label, Select, Textarea), SWR, Vitest

---

### Task 1: Next.js Project Scaffold

**Files:**
- Create: `frontend/` (via create-next-app)
- Modify: `frontend/next.config.ts`
- Modify: `frontend/tailwind.config.ts`
- Create: `frontend/vitest.config.ts`

**Step 1: Scaffold Next.js project**

Run from the repo root (`/Users/lee/Code/claw-bazzar`):

```bash
npx create-next-app@latest frontend \
  --typescript \
  --tailwind \
  --app \
  --no-src-dir \
  --eslint \
  --import-alias "@/*"
```

When prompted interactively, accept all defaults. This creates `frontend/` with Next.js 14, Tailwind, App Router, and TypeScript.

**Step 2: Install shadcn/ui**

```bash
cd frontend && npx shadcn@latest init
```

When prompted:
- Style: **Default**
- Base color: **Slate**
- CSS variables: **Yes**

Then add the components we need:

```bash
npx shadcn@latest add table badge button input label select textarea
```

**Step 3: Install SWR and Vitest**

```bash
npm install swr
npm install -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom
```

**Step 4: Configure API proxy in `frontend/next.config.ts`**

Replace the entire file with:

```typescript
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/:path*',
      },
    ]
  },
}

export default nextConfig
```

**Step 5: Create `frontend/vitest.config.ts`**

```typescript
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
  },
})
```

**Step 6: Add test script to `frontend/package.json`**

In `scripts`, add:
```json
"test": "vitest run"
```

**Step 7: Enable dark mode in `frontend/tailwind.config.ts`**

Ensure `darkMode: 'class'` is set. Open the file and confirm it contains:

```typescript
darkMode: 'class',
```

If it uses `'media'` or is missing, change it to `'class'`.

**Step 8: Verify dev server starts**

```bash
# From /Users/lee/Code/claw-bazzar/frontend
npm run dev
```

Expected: Server starts on `http://localhost:3000` with no errors. Ctrl+C to stop.

**Step 9: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/
git commit -m "chore: scaffold Next.js frontend with shadcn/ui and SWR"
```

---

### Task 2: API Types, Lib, and Utility Functions

**Files:**
- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/utils.ts`
- Create: `frontend/lib/utils.test.ts`

**Step 1: Write failing tests for utility functions**

Create `frontend/lib/utils.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { formatDeadline, scoreColor } from './utils'

describe('formatDeadline', () => {
  it('returns expired for past deadline', () => {
    const past = new Date(Date.now() - 1000).toISOString()
    const result = formatDeadline(past)
    expect(result.expired).toBe(true)
    expect(result.label).toBe('expired')
  })

  it('returns minutes left for deadline under 1 hour', () => {
    const future = new Date(Date.now() + 30 * 60 * 1000).toISOString()
    const result = formatDeadline(future)
    expect(result.expired).toBe(false)
    expect(result.label).toBe('30m left')
  })

  it('returns hours left for deadline between 1–24 hours', () => {
    const future = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString()
    const result = formatDeadline(future)
    expect(result.expired).toBe(false)
    expect(result.label).toBe('2h left')
  })

  it('returns days left for deadline over 24 hours', () => {
    const future = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString()
    const result = formatDeadline(future)
    expect(result.expired).toBe(false)
    expect(result.label).toBe('2d left')
  })
})

describe('scoreColor', () => {
  it('returns muted-foreground for null score', () => {
    expect(scoreColor(null, 0.8)).toBe('text-muted-foreground')
  })

  it('returns green for score at or above threshold', () => {
    expect(scoreColor(0.9, 0.8)).toBe('text-green-400')
    expect(scoreColor(0.8, 0.8)).toBe('text-green-400')
  })

  it('returns yellow for score between 75% and 100% of threshold', () => {
    // threshold=0.8, 75% of threshold = 0.6. Score 0.7 is in [0.6, 0.8)
    expect(scoreColor(0.7, 0.8)).toBe('text-yellow-400')
  })

  it('returns red for score below 75% of threshold', () => {
    // threshold=0.8, 75% of threshold = 0.6. Score 0.3 < 0.6
    expect(scoreColor(0.3, 0.8)).toBe('text-red-400')
  })

  it('returns green when no threshold is set', () => {
    expect(scoreColor(0.5, null)).toBe('text-green-400')
  })
})
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npm test
```

Expected: `FAIL — Cannot find module './utils'`

**Step 3: Implement `frontend/lib/utils.ts`**

```typescript
export function formatDeadline(deadline: string): { label: string; expired: boolean } {
  const diff = new Date(deadline).getTime() - Date.now()
  if (diff <= 0) return { label: 'expired', expired: true }

  const totalMinutes = Math.floor(diff / (1000 * 60))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60

  if (hours >= 24) {
    const days = Math.floor(hours / 24)
    return { label: `${days}d left`, expired: false }
  }
  if (hours >= 1) return { label: `${hours}h left`, expired: false }
  return { label: `${minutes}m left`, expired: false }
}

export function scoreColor(score: number | null, threshold: number | null): string {
  if (score === null) return 'text-muted-foreground'
  if (threshold === null) return 'text-green-400'
  if (score >= threshold) return 'text-green-400'
  if (score >= threshold * 0.75) return 'text-yellow-400'
  return 'text-red-400'
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npm test
```

Expected: all 9 tests `PASS`

**Step 5: Implement `frontend/lib/api.ts`**

```typescript
import useSWR from 'swr'

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`API error: ${r.status}`)
    return r.json()
  })

export interface Task {
  id: string
  title: string
  description: string
  type: 'fastest_first' | 'quality_first'
  threshold: number | null
  max_revisions: number | null
  deadline: string
  status: 'open' | 'closed'
  winner_submission_id: string | null
  created_at: string
}

export interface Submission {
  id: string
  task_id: string
  worker_id: string
  revision: number
  content: string
  score: number | null
  oracle_feedback: string | null
  status: 'pending' | 'scored'
  created_at: string
}

export interface TaskDetail extends Task {
  submissions: Submission[]
}

export function useTasks() {
  return useSWR<Task[]>('/api/tasks', fetcher, { refreshInterval: 30_000 })
}

export function useTask(id: string | null) {
  return useSWR<TaskDetail>(id ? `/api/tasks/${id}` : null, fetcher, {
    refreshInterval: 30_000,
  })
}

export async function createTask(
  data: Pick<Task, 'title' | 'description' | 'type' | 'threshold' | 'max_revisions' | 'deadline'>
): Promise<Task> {
  const resp = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text)
  }
  return resp.json()
}

export async function createSubmission(
  taskId: string,
  data: { worker_id: string; content: string }
): Promise<Submission> {
  const resp = await fetch(`/api/tasks/${taskId}/submissions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text)
  }
  return resp.json()
}
```

**Step 6: Verify TypeScript compiles**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 7: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/lib/
git commit -m "feat: frontend API lib and utility functions with tests"
```

---

### Task 3: Badge Components

**Files:**
- Create: `frontend/components/StatusBadge.tsx`
- Create: `frontend/components/TypeBadge.tsx`

**Step 1: Create `frontend/components/StatusBadge.tsx`**

```tsx
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
```

**Step 2: Create `frontend/components/TypeBadge.tsx`**

```tsx
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
```

**Step 3: Verify compilation**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 4: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/components/StatusBadge.tsx frontend/components/TypeBadge.tsx
git commit -m "feat: StatusBadge and TypeBadge components"
```

---

### Task 4: SubmissionTable & TaskDetail Components

**Files:**
- Create: `frontend/components/SubmissionTable.tsx`
- Create: `frontend/components/TaskDetail.tsx`

**Step 1: Create `frontend/components/SubmissionTable.tsx`**

```tsx
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Submission, Task } from '@/lib/api'
import { scoreColor } from '@/lib/utils'

interface Props {
  submissions: Submission[]
  task: Task
}

export function SubmissionTable({ submissions, task }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Worker</TableHead>
          <TableHead>Rev</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Feedback</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {submissions.map((sub) => {
          const isWinner = sub.id === task.winner_submission_id
          return (
            <TableRow
              key={sub.id}
              className={isWinner ? 'bg-yellow-500/10 border-yellow-500/30' : ''}
            >
              <TableCell className="font-mono text-sm">{sub.worker_id}</TableCell>
              <TableCell>{sub.revision}</TableCell>
              <TableCell className={scoreColor(sub.score, task.threshold)}>
                {sub.score !== null ? sub.score.toFixed(2) : '—'}
                {isWinner && ' 🏆'}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">{sub.status}</TableCell>
              <TableCell className="text-muted-foreground text-sm max-w-xs truncate">
                {sub.oracle_feedback ?? '—'}
              </TableCell>
            </TableRow>
          )
        })}
        {submissions.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} className="text-center text-muted-foreground py-6">
              No submissions yet
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
```

**Step 2: Create `frontend/components/TaskDetail.tsx`**

```tsx
import { TaskDetail as TaskDetailType } from '@/lib/api'
import { StatusBadge } from './StatusBadge'
import { TypeBadge } from './TypeBadge'
import { SubmissionTable } from './SubmissionTable'
import { formatDeadline } from '@/lib/utils'

interface Props {
  task: TaskDetailType
}

export function TaskDetail({ task }: Props) {
  const { label, expired } = formatDeadline(task.deadline)

  return (
    <div className="flex flex-col gap-4 p-6 overflow-auto h-full">
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-xl font-semibold">{task.title}</h2>
        <div className="flex gap-2 shrink-0">
          <TypeBadge type={task.type} />
          <StatusBadge status={task.status} />
        </div>
      </div>

      <p className="text-muted-foreground text-sm leading-relaxed">{task.description}</p>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {task.threshold !== null && (
          <div>
            <span className="text-muted-foreground">Threshold: </span>
            {task.threshold}
          </div>
        )}
        {task.max_revisions !== null && (
          <div>
            <span className="text-muted-foreground">Max Revisions: </span>
            {task.max_revisions}
          </div>
        )}
        <div>
          <span className="text-muted-foreground">Deadline: </span>
          <span className={expired ? 'text-red-400' : ''}>{label}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Winner: </span>
          {task.winner_submission_id
            ? `🏆 ${task.winner_submission_id.slice(0, 8)}…`
            : '—'}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-medium mb-3">
          Submissions ({task.submissions.length})
        </h3>
        <SubmissionTable submissions={task.submissions} task={task} />
      </div>
    </div>
  )
}
```

**Step 3: Verify compilation**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 4: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/components/SubmissionTable.tsx frontend/components/TaskDetail.tsx
git commit -m "feat: SubmissionTable and TaskDetail components"
```

---

### Task 5: TaskTable Component (Left Panel)

**Files:**
- Create: `frontend/components/TaskTable.tsx`

**Step 1: Create `frontend/components/TaskTable.tsx`**

```tsx
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
```

**Step 2: Verify compilation**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 3: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/components/TaskTable.tsx
git commit -m "feat: TaskTable component with filtering and sorting"
```

---

### Task 6: Root Layout & Home Redirect

**Files:**
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/globals.css`

**Step 1: Replace `frontend/app/layout.tsx`**

```tsx
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import Link from 'next/link'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Agent Market',
  description: 'Task marketplace for AI agents',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className={inter.className}>
        <nav className="h-14 border-b border-border flex items-center px-6 gap-6 shrink-0">
          <Link href="/tasks" className="font-bold text-base tracking-tight">
            🕸 Agent Market
          </Link>
          <div className="flex-1" />
          <Link
            href="/dev"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Dev Panel
          </Link>
        </nav>
        {children}
      </body>
    </html>
  )
}
```

**Step 2: Replace `frontend/app/page.tsx`**

```tsx
import { redirect } from 'next/navigation'

export default function Home() {
  redirect('/tasks')
}
```

**Step 3: Verify dark mode classes exist in `frontend/app/globals.css`**

Open the file and confirm it contains a `.dark` block with CSS variables (created by shadcn/ui init). If the dark mode variables are missing, shadcn/ui init may not have run correctly — re-run `npx shadcn@latest init` and choose **Slate** color scheme with CSS variables.

**Step 4: Verify compilation**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 5: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/app/layout.tsx frontend/app/page.tsx frontend/app/globals.css
git commit -m "feat: root layout with dark nav and home redirect"
```

---

### Task 7: Tasks Page (Master-Detail Layout)

**Files:**
- Create: `frontend/app/tasks/page.tsx`

**Step 1: Create `frontend/app/tasks/page.tsx`**

```tsx
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
  const { data: taskDetail } = useTask(selectedId)

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
        {taskDetail ? (
          <TaskDetail task={taskDetail} />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            ← Select a task to view details
          </div>
        )}
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
```

**Step 2: Verify compilation**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 3: Smoke test with live servers**

In terminal 1:
```bash
cd /Users/lee/Code/claw-bazzar && uvicorn app.main:app --reload --port 8000
```

In terminal 2:
```bash
cd /Users/lee/Code/claw-bazzar/frontend && npm run dev
```

Open `http://localhost:3000`. Expected:
- Redirects to `/tasks`
- Left panel shows "Tasks" heading with filter controls
- Right panel shows "← Select a task to view details"
- If no tasks exist yet, left panel shows "No tasks found" (correct — use Dev Panel to create some)

**Step 4: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/app/tasks/
git commit -m "feat: tasks master-detail page"
```

---

### Task 8: Developer Debug Panel

**Files:**
- Create: `frontend/components/DevPanel.tsx`
- Create: `frontend/app/dev/page.tsx`

**Step 1: Create `frontend/components/DevPanel.tsx`**

```tsx
'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { createTask, createSubmission } from '@/lib/api'

export function DevPanel() {
  // Publish form state
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState<'fastest_first' | 'quality_first'>('fastest_first')
  const [threshold, setThreshold] = useState('')
  const [maxRevisions, setMaxRevisions] = useState('')
  const [deadline, setDeadline] = useState('')
  const [publishMsg, setPublishMsg] = useState<string | null>(null)

  // Submit form state
  const [taskId, setTaskId] = useState('')
  const [workerId, setWorkerId] = useState('')
  const [content, setContent] = useState('')
  const [submitMsg, setSubmitMsg] = useState<string | null>(null)

  async function handlePublish(e: React.FormEvent) {
    e.preventDefault()
    setPublishMsg(null)
    try {
      const task = await createTask({
        title,
        description,
        type,
        threshold: threshold ? parseFloat(threshold) : null,
        max_revisions: maxRevisions ? parseInt(maxRevisions, 10) : null,
        deadline: new Date(deadline).toISOString(),
      })
      setPublishMsg(`✅ Published: ${task.id}`)
      setTaskId(task.id)
      setTitle('')
      setDescription('')
      setThreshold('')
      setMaxRevisions('')
      setDeadline('')
    } catch (err) {
      setPublishMsg(`❌ ${(err as Error).message}`)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitMsg(null)
    try {
      const sub = await createSubmission(taskId, { worker_id: workerId, content })
      setSubmitMsg(`✅ Submitted: revision ${sub.revision}, status: ${sub.status}`)
      setContent('')
    } catch (err) {
      setSubmitMsg(`❌ ${(err as Error).message}`)
    }
  }

  return (
    <div className="grid grid-cols-2 gap-10 p-8 max-w-4xl">
      {/* Publish Task */}
      <div>
        <h2 className="text-base font-semibold mb-5">Publish Task</h2>
        <form onSubmit={handlePublish} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Title</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="Task title"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              rows={3}
              placeholder="Describe the task requirements"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Type</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as typeof type)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fastest_first">fastest_first</SelectItem>
                <SelectItem value="quality_first">quality_first</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Threshold{' '}
              <span className="text-muted-foreground text-xs">(fastest_first only)</span>
            </Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              max="1"
              placeholder="0.8"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Max Revisions{' '}
              <span className="text-muted-foreground text-xs">(quality_first only)</span>
            </Label>
            <Input
              type="number"
              min="1"
              placeholder="3"
              value={maxRevisions}
              onChange={(e) => setMaxRevisions(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Deadline</Label>
            <Input
              type="datetime-local"
              required
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          </div>

          <Button type="submit">Publish</Button>

          {publishMsg && (
            <p className="text-sm font-mono break-all">{publishMsg}</p>
          )}
        </form>
      </div>

      {/* Submit Result */}
      <div>
        <h2 className="text-base font-semibold mb-5">Submit Result</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>Task ID</Label>
            <Input
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              required
              placeholder="Auto-filled after publish"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Worker ID</Label>
            <Input
              value={workerId}
              onChange={(e) => setWorkerId(e.target.value)}
              required
              placeholder="my-agent"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Content</Label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              rows={8}
              placeholder="Your submission content..."
            />
          </div>

          <Button type="submit">Submit Result</Button>

          {submitMsg && (
            <p className="text-sm font-mono break-all">{submitMsg}</p>
          )}
        </form>
      </div>
    </div>
  )
}
```

**Step 2: Create `frontend/app/dev/page.tsx`**

```tsx
import { DevPanel } from '@/components/DevPanel'

export default function DevPage() {
  return (
    <div>
      <div className="border-b border-border px-8 py-4 flex items-center gap-3">
        <h1 className="text-lg font-semibold">Developer Panel</h1>
        <span className="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-1 rounded border border-yellow-500/30">
          ⚠ Dev Mode Only
        </span>
      </div>
      <DevPanel />
    </div>
  )
}
```

**Step 3: Verify compilation**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npx tsc --noEmit
```

Expected: no errors

**Step 4: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git add frontend/components/DevPanel.tsx frontend/app/dev/
git commit -m "feat: developer debug panel for publishing tasks and submitting results"
```

---

### Task 9: Full Build Verification & End-to-End Smoke Test

**Files:** none (verification only)

**Step 1: Run full test suite**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npm test
```

Expected: all utility tests `PASS`

**Step 2: Run production build**

```bash
cd /Users/lee/Code/claw-bazzar/frontend && npm run build
```

Expected: build succeeds with no TypeScript errors. You'll see output like:

```
✓ Compiled successfully
Route (app)               Size
├ ○ /                     ...
├ ○ /dev                  ...
└ ○ /tasks                ...
```

**Step 3: End-to-end smoke test**

Start both servers:

```bash
# Terminal 1
cd /Users/lee/Code/claw-bazzar && uvicorn app.main:app --reload --port 8000

# Terminal 2
cd /Users/lee/Code/claw-bazzar/frontend && npm run dev
```

Verify the following manually:

1. `http://localhost:3000` → redirects to `/tasks` ✓
2. `/tasks` → left panel shows filters, right panel shows placeholder ✓
3. Navigate to `/dev` → two-column form renders ✓
4. Publish a `fastest_first` task (threshold 0.8, deadline 1 hour from now) → success message appears, Task ID auto-fills in Submit form ✓
5. Navigate to `/tasks` → new task appears in list ✓
6. Click the task → right panel shows task detail with empty submissions table ✓
7. Back to `/dev`, submit a result for that task → success message ✓
8. Back to `/tasks`, click task → submission appears in table with `pending` status ✓
9. Wait ~30 seconds → if oracle ran, status updates to `scored` with score 0.9 ✓
10. Reload `/tasks?id=<task-id>` directly → detail panel restores from URL ✓

**Step 4: Commit**

```bash
cd /Users/lee/Code/claw-bazzar
git commit -m "chore: verified frontend build and smoke test"
```

---

## Running the Full Stack

```bash
# Terminal 1 — FastAPI backend
cd /Users/lee/Code/claw-bazzar
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Next.js frontend
cd /Users/lee/Code/claw-bazzar/frontend
npm run dev
```

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API via frontend proxy: `http://localhost:3000/api/tasks`
