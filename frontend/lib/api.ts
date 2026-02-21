import useSWR from 'swr'

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`API error: ${r.status}`)
    return r.json()
  })

export type PayoutStatus = 'pending' | 'paid' | 'failed'
export type UserRole = 'publisher' | 'worker'

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
  publisher_id: string | null
  bounty: number | null
  payment_tx_hash: string | null
  payout_status: PayoutStatus | null
  payout_tx_hash: string | null
  payout_amount: number | null
}

export interface User {
  id: string
  nickname: string
  wallet: string
  role: UserRole
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
  data: Pick<Task, 'title' | 'description' | 'type' | 'threshold' | 'max_revisions' | 'deadline' | 'publisher_id' | 'bounty'>,
  paymentHeader?: string,
): Promise<Task> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (paymentHeader) {
    headers['X-PAYMENT'] = paymentHeader
  }
  const resp = await fetch('/api/tasks', {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text)
  }
  return resp.json()
}

export async function registerUser(
  data: { nickname: string; wallet: string; role: UserRole },
): Promise<User> {
  const resp = await fetch('/api/users', {
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

export function useUser(id: string | null) {
  return useSWR<User>(id ? `/api/users/${id}` : null, fetcher, {
    refreshInterval: 30_000,
  })
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
