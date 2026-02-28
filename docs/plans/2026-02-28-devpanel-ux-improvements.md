# DevPanel UX Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 改善 DevPanel 的开发体验，涵盖六项增强：接收标准动态列表、任务 ID 醒目展示、多 Worker 提交状态看板、Oracle Feedback 结构化展示、任务生命周期进度条、Oracle Log 输出可展开查看。

**Architecture:** 全部变更集中在前端 `DevPanel.tsx` 与后端 `app/services/oracle.py`。前端新增若干纯展示子组件（`TaskStatusStepper`、`FeedbackCard`），无需新路由；后端仅给 oracle log entry 补充 `output` 字段。`lib/api.ts` 同步补全 `Submission.status` 类型。

**Tech Stack:** Next.js 15 / React / TypeScript / TailwindCSS / Vitest（前端），FastAPI / Python（后端）

---

## 背景与现状

- `frontend/components/DevPanel.tsx`（1232 行）：4 列布局，Register | Publish | Submit | Arbiter+OracleLogs+History
- `frontend/lib/api.ts`：`Submission.status` 仅 `'pending' | 'scored'`，缺少 `gate_passed / gate_failed / policy_violation`
- `app/services/oracle.py`：`_call_oracle` 记录 log 但不存 oracle 输出内容
- oracle feedback 结构：`{ type: "gate_check"|"individual_scoring"|"scoring", ... }`（V3 结构化 JSON）

---

### Task A: 补全 Submission 类型 + acceptance_criteria 动态列表

**Files:**
- Modify: `frontend/lib/api.ts:67`
- Modify: `frontend/components/DevPanel.tsx`（acceptance_criteria 相关：约 355 行 state、614 行提交逻辑、826–831 行 UI）

**Step 1: 更新 api.ts 中 Submission.status 类型**

在 `frontend/lib/api.ts` 第 67 行将：
```typescript
status: 'pending' | 'scored'
```
改为：
```typescript
status: 'pending' | 'gate_passed' | 'gate_failed' | 'policy_violation' | 'scored'
```

**Step 2: 更新 DevPanel state**

找到当前的 `const [acceptanceCriteria, setAcceptanceCriteria] = useState('')`（约第 355 行），替换为：
```typescript
const [criteria, setCriteria] = useState<string[]>([''])
```

**Step 3: 更新发布逻辑**

找到 `handlePublish` 中的：
```typescript
acceptance_criteria: acceptanceCriteria
  .split('\n')
  .map((s) => s.trim())
  .filter(Boolean),
```
替换为：
```typescript
acceptance_criteria: criteria.map((s) => s.trim()).filter(Boolean),
```

还要找清空逻辑 `setAcceptanceCriteria('')`，改为 `setCriteria([''])`.

**Step 4: 替换 UI — Acceptance Criteria 表单区块**

找到当前的 Textarea 区块（约 820–831 行）：
```tsx
<div className="flex flex-col gap-1.5">
  <Label>
    Acceptance Criteria{' '}
    <span className="text-muted-foreground text-xs">(drives Oracle V2 gate check + scoring dimensions)</span>
  </Label>
  <Textarea
    value={acceptanceCriteria}
    onChange={(e) => setAcceptanceCriteria(e.target.value)}
    rows={3}
    placeholder={"1. 至少列出5个工具\n2. 每个包含名称和官网\n3. 信息必须真实"}
  />
</div>
```
替换为：
```tsx
<div className="flex flex-col gap-1.5">
  <Label>
    Acceptance Criteria{' '}
    <span className="text-muted-foreground text-xs">(Oracle V3 gate check + scoring dimensions)</span>
  </Label>
  <div className="flex flex-col gap-1.5">
    {criteria.map((item, idx) => (
      <div key={idx} className="flex gap-1.5 items-center">
        <span className="text-muted-foreground text-xs w-4 shrink-0 text-right">{idx + 1}.</span>
        <Input
          value={item}
          onChange={(e) => {
            const next = [...criteria]
            next[idx] = e.target.value
            setCriteria(next)
          }}
          placeholder="验收标准条目"
          className="flex-1 text-sm"
        />
        {criteria.length > 1 && (
          <button
            type="button"
            onClick={() => setCriteria(criteria.filter((_, i) => i !== idx))}
            className="text-muted-foreground hover:text-red-400 text-sm w-5 shrink-0"
          >
            ×
          </button>
        )}
      </div>
    ))}
    <button
      type="button"
      onClick={() => setCriteria([...criteria, ''])}
      className="text-xs text-blue-400 hover:text-blue-300 text-left mt-0.5 pl-5"
    >
      + Add criterion
    </button>
  </div>
</div>
```

**Step 5: 验证 lint 通过**

```bash
cd frontend && npm run lint
```
Expected: 无新增错误。

**Step 6: Commit**

```bash
git add frontend/lib/api.ts frontend/components/DevPanel.tsx
git commit -m "feat(devpanel): acceptance_criteria 改为动态列表输入，补全 Submission status 类型"
```

---

### Task B: TaskStatusStepper 组件 + 任务 ID 条

**Files:**
- Create: `frontend/components/TaskStatusStepper.tsx`
- Modify: `frontend/components/DevPanel.tsx`（Publish 结果卡 + Submit 列顶部）

**Step 1: 创建 TaskStatusStepper 组件**

新建 `frontend/components/TaskStatusStepper.tsx`：

```tsx
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
    <div className="flex items-start gap-0 mt-1">
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
                  'h-px w-6 mt-[-10px]',
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
```

**Step 2: 在 Publish 结果卡内嵌入 Stepper**

在 `DevPanel.tsx` 顶部 import 列表加：
```tsx
import { TaskStatusStepper } from '@/components/TaskStatusStepper'
```

在 `publishedTask` 的结果卡（约 960 行 `<div className="p-3 bg-zinc-900...">`）内，找 `Status:` 那行：
```tsx
<p className="text-muted-foreground">
  Status: <span className="text-white">{publishedTask.status}</span>
</p>
```
在其**下方**插入：
```tsx
<TaskStatusStepper type={publishedTask.type} status={publishedTask.status} />
```

**Step 3: 在 Submit 列顶部增加 Task Info 条**

在 Submit 列（约第 1017 行 `<div>` 的 `<h2>Submit Result</h2>` 下方，worker selector 上方）插入一个 task 信息条：

```tsx
{/* Current Task Info */}
{(publishedTask || taskId) && (
  <div className="mb-4 p-2.5 bg-zinc-900 border border-zinc-700 rounded text-xs space-y-1.5">
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground shrink-0">Task ID:</span>
      <span
        className="font-mono text-blue-300 break-all cursor-pointer hover:text-blue-200 flex-1"
        title="点击复制"
        onClick={() => navigator.clipboard.writeText(taskId)}
      >
        {taskId || '—'}
      </span>
    </div>
    {publishedTask && (
      <TaskStatusStepper type={publishedTask.type} status={publishedTask.status} />
    )}
  </div>
)}
```

**Step 4: Commit**

```bash
git add frontend/components/TaskStatusStepper.tsx frontend/components/DevPanel.tsx
git commit -m "feat(devpanel): TaskStatusStepper 任务阶段进度条 + Submit 列顶部 task info 条"
```

---

### Task C: 多 Worker 提交状态看板

**Files:**
- Modify: `frontend/components/DevPanel.tsx`（state、handleSubmit、polling、UI）

**Step 1: 替换 trackedSub/polledSub 为 per-worker 状态**

当前的 state：
```typescript
const [trackedSub, setTrackedSub] = useState<Submission | null>(null)
const [polledSub, setPolledSub] = useState<Submission | null>(null)
const [polledTask, setPolledTask] = useState<TaskDetail | null>(null)
```
替换为：
```typescript
// 存每个 worker 最新提交 (keyed by storageKey)
const [workerSubs, setWorkerSubs] = useState<Record<string, Submission>>({})
const [polledTask, setPolledTask] = useState<TaskDetail | null>(null)
const [isPolling, setIsPolling] = useState(false)
```

**Step 2: 更新 handleSubmit**

找到 `handleSubmit` 函数中：
```typescript
const sub = await createSubmission(taskId, { worker_id: workerId, content })
setTrackedSub(sub)
setPolledSub(sub)
setContent('')
setChallengeTaskId(taskId)
setChallengeSubId(sub.id)
```
替换为：
```typescript
const sub = await createSubmission(taskId, { worker_id: workerId, content })
setWorkerSubs(prev => ({ ...prev, [activeWorker!.storageKey]: sub }))
setContent('')
setChallengeTaskId(taskId)
setChallengeSubId(sub.id)
setIsPolling(true)
```

**Step 3: 替换轮询 useEffect**

找到原来的轮询 `useEffect`（监听 `trackedSub` 的那段，约 523–549 行），替换为：
```typescript
// Poll task submissions whenever isPolling=true and taskId is set
useEffect(() => {
  if (!isPolling || !taskId) return

  const TERMINAL = new Set(['scored', 'gate_failed', 'policy_violation'])

  const tick = async () => {
    try {
      const resp = await fetch(`/api/tasks/${taskId}`)
      if (!resp.ok) return
      const task: TaskDetail = await resp.json()
      setPolledTask(task)

      // Update workerSubs for all known workers
      setWorkerSubs(prev => {
        const next = { ...prev }
        for (const w of DEV_WORKERS) {
          const wId = workerIds[DEV_WORKERS.indexOf(w)]
          if (!wId) continue
          const found = task.submissions.find(s => s.worker_id === wId)
          if (found) next[w.storageKey] = found
        }
        return next
      })

      // Stop polling when all tracked subs are terminal
      const allDone = Object.values(workerSubs).every(
        s => TERMINAL.has(s.status) || (s.status === 'gate_passed' && s.oracle_feedback)
      )
      if (allDone && Object.keys(workerSubs).length > 0) {
        setIsPolling(false)
      }
    } catch {}
  }

  tick()
  const id = setInterval(tick, 2000)
  return () => clearInterval(id)
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [isPolling, taskId, workerIds])
```

**Step 4: 替换提交结果展示 UI**

找到原来的 `{polledSub && (<div ...>...` 大块（约 1083–1140 行）并**完整替换**为 Worker 状态看板：

```tsx
{/* Worker Status Board */}
{Object.keys(workerSubs).length > 0 && (
  <div className="mt-2 border border-zinc-700 rounded overflow-hidden text-xs">
    <div className="px-3 py-1.5 bg-zinc-900 text-muted-foreground flex items-center gap-2">
      <span className="font-medium text-white">提交状态</span>
      {isPolling && (
        <span className="inline-block w-2.5 h-2.5 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
      )}
    </div>
    <div className="divide-y divide-zinc-800">
      {DEV_WORKERS.map((w, i) => {
        const sub = workerSubs[w.storageKey]
        if (!sub) return null
        const isActive = i === activeWorkerIdx
        return (
          <WorkerSubRow
            key={w.storageKey}
            worker={w}
            sub={sub}
            isActive={isActive}
            maxRevisions={polledTask?.max_revisions ?? publishedTask?.max_revisions ?? null}
            onClick={() => {
              setActiveWorkerIdx(i)
              setWorkerId(workerIds[i] || '')
            }}
          />
        )
      })}
    </div>
  </div>
)}
```

**Step 5: 新增 WorkerSubRow 子组件（写在 DevPanel 函数上方）**

在 `export function DevPanel()` 上方添加：

```tsx
function statusColor(status: Submission['status']): string {
  switch (status) {
    case 'scored': return 'text-green-400'
    case 'gate_passed': return 'text-blue-400'
    case 'gate_failed': return 'text-red-400'
    case 'policy_violation': return 'text-orange-400'
    default: return 'text-yellow-400'
  }
}

function statusLabel(status: Submission['status']): string {
  switch (status) {
    case 'scored': return '已评分'
    case 'gate_passed': return 'Gate ✓'
    case 'gate_failed': return 'Gate ✗'
    case 'policy_violation': return '违规'
    default: return '评分中…'
  }
}

interface WorkerSubRowProps {
  worker: import('@/lib/dev-wallets').DevUser
  sub: Submission
  isActive: boolean
  maxRevisions: number | null
  onClick: () => void
}

function WorkerSubRow({ worker, sub, isActive, maxRevisions, onClick }: WorkerSubRowProps) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div
      className={['px-3 py-2 cursor-pointer hover:bg-zinc-900/60', isActive ? 'bg-zinc-900/40' : ''].join(' ')}
      onClick={onClick}
    >
      <div className="flex items-center gap-2">
        <span className={['font-medium w-16 shrink-0', isActive ? 'text-blue-300' : 'text-white'].join(' ')}>
          {worker.nickname}
        </span>
        <span className={['font-medium shrink-0', statusColor(sub.status)].join(' ')}>
          {statusLabel(sub.status)}
        </span>
        {sub.score !== null && (
          <span className="font-mono text-white shrink-0">{sub.score.toFixed(1)}</span>
        )}
        <span className="text-muted-foreground font-mono truncate flex-1" title={sub.id}>
          {sub.id.slice(0, 8)}…
        </span>
        {maxRevisions && (
          <span className="text-muted-foreground shrink-0">r{sub.revision}/{maxRevisions}</span>
        )}
        {sub.oracle_feedback && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            className="text-muted-foreground hover:text-white shrink-0 ml-1"
          >
            {expanded ? '▲' : '▼'}
          </button>
        )}
      </div>
      {expanded && sub.oracle_feedback && (
        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
          <FeedbackCard raw={sub.oracle_feedback} />
        </div>
      )}
    </div>
  )
}
```

**Step 6: Commit**

```bash
git add frontend/components/DevPanel.tsx
git commit -m "feat(devpanel): 多 Worker 提交状态看板，per-worker 轮询"
```

---

### Task D: FeedbackCard 结构化 Feedback 展示

**Files:**
- Create: `frontend/components/FeedbackCard.tsx`
- Modify: `frontend/components/DevPanel.tsx`（import FeedbackCard）

**Step 1: 创建 FeedbackCard 组件**

新建 `frontend/components/FeedbackCard.tsx`：

```tsx
'use client'
import { useState } from 'react'

interface GateCheckResult {
  criterion: string
  passed: boolean
  reason?: string
}

interface GateCheckFeedback {
  type: 'gate_check'
  overall_passed: boolean
  criteria_results?: GateCheckResult[]
  summary?: string
}

interface DimensionScore {
  band: string
  score: number
  evidence?: string
  feedback?: string
}

interface RevisionSuggestion {
  problem: string
  suggestion: string
  severity: 'high' | 'medium' | 'low'
}

interface IndividualScoringFeedback {
  type: 'individual_scoring'
  dimension_scores?: Record<string, DimensionScore>
  overall_band?: string
  revision_suggestions?: RevisionSuggestion[]
}

interface ScoringFeedback {
  type: 'scoring'
  gate_check?: { overall_passed: boolean; summary?: string }
  dimension_scores?: Record<string, DimensionScore>
  overall_band?: string
  revision_suggestions?: RevisionSuggestion[]
  passed?: boolean
}

type OracleFeedback = GateCheckFeedback | IndividualScoringFeedback | ScoringFeedback

const SEVERITY_COLOR: Record<string, string> = {
  high: 'text-red-400',
  medium: 'text-yellow-400',
  low: 'text-zinc-400',
}

const BAND_COLOR: Record<string, string> = {
  A: 'text-green-400',
  B: 'text-blue-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  E: 'text-red-400',
}

function BandBadge({ band }: { band: string }) {
  return (
    <span className={['font-mono font-bold', BAND_COLOR[band] ?? 'text-white'].join(' ')}>
      [{band}]
    </span>
  )
}

function DimTable({ dims }: { dims: Record<string, DimensionScore> }) {
  return (
    <table className="w-full text-[11px] mt-1">
      <thead>
        <tr className="text-muted-foreground border-b border-zinc-800">
          <th className="text-left py-0.5 font-normal">维度</th>
          <th className="text-center py-0.5 font-normal w-8">Band</th>
          <th className="text-right py-0.5 font-normal w-10">分数</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(dims).map(([id, d]) => (
          <tr key={id} className="border-b border-zinc-800/50" title={d.evidence}>
            <td className="py-0.5 text-muted-foreground pr-2">{id}</td>
            <td className="py-0.5 text-center"><BandBadge band={d.band} /></td>
            <td className="py-0.5 text-right font-mono text-white">{d.score}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Suggestions({ suggestions }: { suggestions: RevisionSuggestion[] }) {
  return (
    <div className="space-y-1.5">
      {suggestions.map((s, i) => (
        <div key={i} className="flex gap-1.5">
          <span className={['shrink-0 uppercase text-[9px] font-bold w-8 mt-0.5', SEVERITY_COLOR[s.severity]].join(' ')}>
            {s.severity.slice(0, 3)}
          </span>
          <div>
            <p className="text-white leading-tight">{s.problem}</p>
            <p className="text-muted-foreground leading-tight">→ {s.suggestion}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

export function FeedbackCard({ raw }: { raw: string }) {
  const [showDims, setShowDims] = useState(false)
  let data: OracleFeedback
  try {
    data = JSON.parse(raw)
  } catch {
    return <p className="text-muted-foreground text-[11px] break-all">{raw}</p>
  }

  if (data.type === 'gate_check') {
    return (
      <div className="space-y-1 text-[11px]">
        <div className="flex items-center gap-2">
          <span className={data.overall_passed ? 'text-green-400 font-medium' : 'text-red-400 font-medium'}>
            Gate {data.overall_passed ? '✓ 通过' : '✗ 未通过'}
          </span>
        </div>
        {data.summary && <p className="text-muted-foreground">{data.summary}</p>}
        {!data.overall_passed && data.criteria_results && (
          <ul className="space-y-0.5 pl-2">
            {data.criteria_results.filter(c => !c.passed).map((c, i) => (
              <li key={i} className="text-red-300">✗ {c.criterion}{c.reason ? `：${c.reason}` : ''}</li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  if (data.type === 'individual_scoring') {
    return (
      <div className="space-y-2 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-medium">个人评分</span>
          {data.overall_band && <BandBadge band={data.overall_band} />}
        </div>
        {data.revision_suggestions && data.revision_suggestions.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1">修订建议：</p>
            <Suggestions suggestions={data.revision_suggestions} />
          </div>
        )}
        {data.dimension_scores && (
          <div>
            <button
              type="button"
              onClick={() => setShowDims(!showDims)}
              className="text-muted-foreground hover:text-white"
            >
              {showDims ? '▲ 隐藏维度详情' : '▼ 查看维度详情'}
            </button>
            {showDims && <DimTable dims={data.dimension_scores} />}
          </div>
        )}
      </div>
    )
  }

  if (data.type === 'scoring') {
    return (
      <div className="space-y-2 text-[11px]">
        <div className="flex items-center gap-2">
          {data.gate_check && (
            <span className={data.gate_check.overall_passed ? 'text-green-400' : 'text-red-400'}>
              Gate {data.gate_check.overall_passed ? '✓' : '✗'}
            </span>
          )}
          {data.overall_band && <BandBadge band={data.overall_band} />}
        </div>
        {data.revision_suggestions && data.revision_suggestions.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1">修订建议：</p>
            <Suggestions suggestions={data.revision_suggestions} />
          </div>
        )}
        {data.dimension_scores && (
          <div>
            <button
              type="button"
              onClick={() => setShowDims(!showDims)}
              className="text-muted-foreground hover:text-white"
            >
              {showDims ? '▲ 隐藏' : '▼ 维度详情'}
            </button>
            {showDims && <DimTable dims={data.dimension_scores} />}
          </div>
        )}
      </div>
    )
  }

  // Fallback: raw JSON
  return (
    <pre className="text-[10px] text-muted-foreground overflow-auto max-h-32 whitespace-pre-wrap break-all">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
```

**Step 2: DevPanel 导入 FeedbackCard**

在 `DevPanel.tsx` 顶部 import 区加：
```tsx
import { FeedbackCard } from '@/components/FeedbackCard'
```

（`WorkerSubRow` 中已经使用了 `<FeedbackCard raw={sub.oracle_feedback} />`，Task C 已埋好占位，这步补 import 即可）

**Step 3: Commit**

```bash
git add frontend/components/FeedbackCard.tsx frontend/components/DevPanel.tsx
git commit -m "feat(devpanel): FeedbackCard 结构化展示 Oracle V3 gate/individual/scoring feedback"
```

---

### Task E: Oracle Log 记录输出内容

**Files:**
- Modify: `app/services/oracle.py`（`_call_oracle` 函数，约 110–127 行）
- Modify: `frontend/components/DevPanel.tsx`（OracleLog interface + 行展开 UI）

**Step 1: 后端 log entry 加 output 字段**

在 `app/services/oracle.py` 的 `_call_oracle` 函数中，找到 `log_entry = { ... }` 块，在 `"duration_ms": duration_ms,` 之后加一行：

```python
"output": output,  # 完整 oracle 输出（不含 _token_usage）
```

注意：`output` 此时已经通过 `output.pop("_token_usage", None)` 去掉了 token usage，所以直接记录即可。

完整修改后的 log_entry：
```python
log_entry = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mode": payload.get("mode", "unknown"),
    "task_id": m.get("task_id", ""),
    "task_title": m.get("task_title", ""),
    "submission_id": m.get("submission_id", ""),
    "worker_id": m.get("worker_id", ""),
    "model": os.environ.get("ORACLE_LLM_MODEL", ""),
    "prompt_tokens": token_usage.get("prompt_tokens", 0),
    "completion_tokens": token_usage.get("completion_tokens", 0),
    "total_tokens": token_usage.get("total_tokens", 0),
    "duration_ms": duration_ms,
    "output": output,  # 完整 oracle 输出
}
```

但注意：当 `token_usage` 为 None（V1 stub path，无 `_token_usage` 字段），这条 log 本来就不记录。现在需要也记录无 token_usage 的调用，确认是否要改——**不改**，保持现有行为：只记录有 token_usage 的 V3 调用。

**Step 2: 前端 OracleLog interface 加 output 字段**

在 `DevPanel.tsx` 的 `interface OracleLog` 加一行：
```typescript
output?: unknown
```

**Step 3: 前端 log 行 UI 加展开按钮**

找到 Individual log rows 的渲染（约 290–310 行）：
```tsx
<div key={i} className="flex items-center gap-3 text-[11px] pl-2 py-0.5 hover:bg-zinc-900/50 rounded">
  <span className="font-mono text-muted-foreground w-16 shrink-0">
    {new Date(log.timestamp).toLocaleTimeString()}
  </span>
  <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-white shrink-0">
    {log.mode}
  </span>
  <span className="text-muted-foreground ml-auto tabular-nums">
    {log.prompt_tokens.toLocaleString()}
    <span className="text-zinc-600 mx-0.5">/</span>
    {log.completion_tokens.toLocaleString()}
    <span className="text-zinc-600 mx-0.5">/</span>
    <span className="text-white">{log.total_tokens.toLocaleString()}</span>
  </span>
  <span className="font-mono text-muted-foreground w-14 text-right shrink-0">
    {formatDuration(log.duration_ms)}
  </span>
</div>
```

这段 log row 需要本地 expanded 状态，把它提取为一个小组件 `OracleLogRow`（写在 `OracleLogsPanel` 函数之前）：

```tsx
function OracleLogRow({ log }: { log: OracleLog }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div>
      <div className="flex items-center gap-3 text-[11px] pl-2 py-0.5 hover:bg-zinc-900/50 rounded">
        <span className="font-mono text-muted-foreground w-16 shrink-0">
          {new Date(log.timestamp).toLocaleTimeString()}
        </span>
        <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-white shrink-0">
          {log.mode}
        </span>
        <span className="text-muted-foreground ml-auto tabular-nums">
          {log.prompt_tokens.toLocaleString()}
          <span className="text-zinc-600 mx-0.5">/</span>
          {log.completion_tokens.toLocaleString()}
          <span className="text-zinc-600 mx-0.5">/</span>
          <span className="text-white">{log.total_tokens.toLocaleString()}</span>
        </span>
        <span className="font-mono text-muted-foreground w-14 text-right shrink-0">
          {formatDuration(log.duration_ms)}
        </span>
        {log.output !== undefined && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="text-muted-foreground hover:text-white text-[10px] w-4 shrink-0"
          >
            {expanded ? '▲' : '▼'}
          </button>
        )}
      </div>
      {expanded && log.output !== undefined && (
        <pre className="text-[10px] text-muted-foreground bg-zinc-950 rounded mx-2 mt-1 p-2 max-h-48 overflow-auto whitespace-pre-wrap break-all">
          {JSON.stringify(log.output, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

在 `OracleLogsPanel` 里把原来的 `<div key={i} className="flex items-center gap-3 ...">...</div>` 替换为：
```tsx
<OracleLogRow key={i} log={log} />
```

**Step 4: Commit**

```bash
git add app/services/oracle.py frontend/components/DevPanel.tsx
git commit -m "feat(devpanel): oracle log 记录输出内容，前端可展开查看 JSON"
```

---

### Task F: 端到端验证

**Step 1: 启动服务**

两个终端：
```bash
# Terminal 1
uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

**Step 2: 验证 acceptance_criteria 动态列表**
- 打开 DevPanel，Publish 区有多行 Input + Add/Remove 按钮
- 发布任务后查看后端 `/api/tasks` 返回的 `acceptance_criteria` 字段为数组

**Step 3: 验证 TaskStatusStepper**
- Publish 区发布任务后出现进度条（fastest_first: 2步；quality_first: 5步）
- Submit 列顶部出现 task info 条含进度条

**Step 4: 验证 Worker 状态看板**
- 以 Alice 提交内容后，Submit 列下方出现状态行，显示 `gate_passed/gate_failed/pending`
- 切换到 Bob 再提交，状态看板出现两行

**Step 5: 验证 FeedbackCard**
- 点击状态行的 ▼ 展开，看到结构化 feedback（gate pass/fail、Band、修订建议）

**Step 6: 验证 Oracle Log 输出展开**
- Oracle Logs Panel 每条 log 行右侧出现 ▼ 按钮
- 点击展开看到格式化 JSON 输出

**Step 7: 最终 lint + 前端测试**
```bash
cd frontend && npm run lint && npm test
```
Expected: 无错误，22 个测试全绿。

**Step 8: Commit**
```bash
git add .
git commit -m "chore: devpanel ux improvements 端到端验证通过"
```
