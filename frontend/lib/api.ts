import useSWR from 'swr'

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`API error: ${r.status}`)
    return r.json()
  })

export type PayoutStatus = 'pending' | 'paid' | 'failed' | 'refunded'
export type UserRole = 'publisher' | 'worker'
export type TaskStatus = 'open' | 'scoring' | 'challenge_window' | 'arbitrating' | 'closed' | 'voided'
export type ChallengeVerdict = 'upheld' | 'rejected' | 'malicious'
export type ChallengeStatus = 'pending' | 'judged'
export type TrustTier = 'S' | 'A' | 'B' | 'C'
export type ArbiterVerdictType = 'upheld' | 'rejected' | 'malicious'

export interface ScoringDimension {
  name: string
  description: string
}

export interface Task {
  id: string
  title: string
  description: string
  type: 'fastest_first' | 'quality_first'
  threshold: number | null
  max_revisions: number | null
  deadline: string
  status: TaskStatus
  winner_submission_id: string | null
  created_at: string
  publisher_id: string | null
  publisher_nickname?: string | null
  bounty: number | null
  payment_tx_hash: string | null
  payout_status: PayoutStatus | null
  payout_tx_hash: string | null
  payout_amount: number | null
  submission_deposit: number | null
  challenge_duration: number | null
  acceptance_criteria: string[]
  escrow_tx_hash: string | null
  scoring_dimensions: ScoringDimension[]
}

export interface User {
  id: string
  nickname: string
  wallet: string
  role: UserRole
  created_at: string
  trust_score: number
  trust_tier: TrustTier
  github_id: string | null
  is_arbiter: boolean
  staked_amount: number
}

export interface Submission {
  id: string
  task_id: string
  worker_id: string
  revision: number
  content: string
  score: number | null
  oracle_feedback: string | null
  status: 'pending' | 'gate_passed' | 'gate_failed' | 'policy_violation' | 'scored'
  created_at: string
}

export interface Challenge {
  id: string
  task_id: string
  challenger_submission_id: string
  target_submission_id: string
  reason: string
  verdict: ChallengeVerdict | null
  arbiter_feedback: string | null
  arbiter_score: number | null
  status: ChallengeStatus
  challenger_wallet: string | null
  deposit_tx_hash: string | null
  created_at: string
}

export interface TrustProfile {
  trust_score: number
  trust_tier: TrustTier
  challenge_deposit_rate: number
  platform_fee_rate: number
  can_accept_tasks: boolean
  can_challenge: boolean
  max_task_amount: number | null
  is_arbiter: boolean
  github_bound: boolean
  staked_amount: number
  stake_bonus: number
  consolation_total: number
}

export interface TrustEvent {
  id: string
  event_type: string
  task_id: string | null
  amount: number
  delta: number
  score_before: number
  score_after: number
  created_at: string
}

export interface BalanceEvent {
  id: string
  event_type: string
  role: string
  task_id: string | null
  task_title: string | null
  amount: number
  direction: 'inflow' | 'outflow'
  tx_hash: string | null
  created_at: string
}

export interface TrustQuote {
  trust_tier: TrustTier
  challenge_deposit_rate: number
  challenge_deposit_amount: number
  platform_fee_rate: number
  service_fee: number
}

export interface ArbiterVote {
  id: string
  challenge_id: string
  arbiter_user_id: string
  vote: ArbiterVerdictType | null
  feedback: string | null
  is_majority: boolean | null
  reward_amount: number | null
  created_at: string
}

export interface WeeklyLeaderboardEntry {
  user_id: string
  nickname: string
  total_earned: number
  trust_score: number
  trust_tier: TrustTier
  rank: number
}

export interface TaskDetail extends Task {
  submissions: Submission[]
}

/* ── Settlement ── */

export interface SettlementSource {
  label: string
  amount: number
  type: 'bounty' | 'incentive' | 'deposit'
  verdict: ChallengeVerdict | null
}

export interface SettlementDistribution {
  label: string
  amount: number
  type: 'winner' | 'refund' | 'arbiter' | 'platform' | 'publisher_refund'
  wallet: string | null
  nickname: string | null
}

export interface SettlementSummary {
  winner_payout: number
  winner_nickname: string | null
  winner_tier: TrustTier | null
  payout_rate: number
  deposits_forfeited: number
  deposits_refunded: number
  arbiter_reward_total: number
  platform_fee: number
}

export interface SettlementTrustChange {
  nickname: string
  user_id: string
  event_type: string
  delta: number
  score_before: number
  score_after: number
}

export interface Settlement {
  escrow_total: number
  sources: SettlementSource[]
  distributions: SettlementDistribution[]
  resolve_tx_hash: string | null
  summary: SettlementSummary
  trust_changes: SettlementTrustChange[]
}

/* ── Merged Arbitration (Jury Ballots) ── */

export interface JuryBallot {
  id: string
  task_id: string
  arbiter_user_id: string
  winner_submission_id: string | null
  feedback: string | null
  coherence_status: string | null
  is_majority: boolean | null
  created_at: string
  voted_at: string | null
  malicious_tags: string[]
}

export function useTasks() {
  return useSWR<Task[]>('/api/tasks', fetcher, { refreshInterval: 30_000 })
}

export function useTask(id: string | null) {
  return useSWR<TaskDetail>(id ? `/api/tasks/${id}` : null, fetcher, {
    refreshInterval: 30_000,
  })
}

export function useChallenges(taskId: string | null) {
  return useSWR<Challenge[]>(
    taskId ? `/api/tasks/${taskId}/challenges` : null,
    fetcher,
    { refreshInterval: 10_000 },
  )
}

export function useJuryBallots(taskId: string | null) {
  return useSWR<JuryBallot[]>(
    taskId ? `/api/tasks/${taskId}/jury-ballots` : null,
    fetcher,
    { refreshInterval: 10_000 },
  )
}

export function useTrustProfile(userId: string | null) {
  return useSWR<TrustProfile>(userId ? `/api/users/${userId}/trust` : null, fetcher, {
    refreshInterval: 30_000,
  })
}

export function useTrustEvents(userId: string | null) {
  return useSWR<TrustEvent[]>(userId ? `/api/users/${userId}/trust/events` : null, fetcher, {
    refreshInterval: 30_000,
  })
}

export function useBalanceEvents(userId: string | null) {
  return useSWR<BalanceEvent[]>(userId ? `/api/users/${userId}/balance-events` : null, fetcher, {
    refreshInterval: 30_000,
  })
}

export function useArbiterVotes(challengeId: string | null, viewerId?: string | null) {
  const params = viewerId ? `?viewer_id=${viewerId}` : ''
  return useSWR<ArbiterVote[]>(
    challengeId ? `/api/challenges/${challengeId}/votes${params}` : null,
    fetcher,
    { refreshInterval: 10_000 },
  )
}

export function useSettlement(taskId: string | null) {
  return useSWR<Settlement>(
    taskId ? `/api/tasks/${taskId}/settlement` : null,
    fetcher,
    { refreshInterval: 30_000 },
  )
}

export interface UserStats {
  tasks_participated: number
  tasks_won: number
  win_rate: number
  total_earned: number
  malicious_count: number
  submissions_last_30d: number
  registered_at: string
}

export function useUserStats(userId: string | null) {
  return useSWR<UserStats>(userId ? `/api/users/${userId}/stats` : null, fetcher, {
    refreshInterval: 30_000,
  })
}

export function useWeeklyLeaderboard() {
  return useSWR<WeeklyLeaderboardEntry[]>('/api/leaderboard/weekly', fetcher, {
    refreshInterval: 60_000,
  })
}

export async function createTask(
  data: Pick<Task, 'title' | 'description' | 'type' | 'threshold' | 'max_revisions' | 'deadline' | 'publisher_id' | 'bounty'>
    & Partial<Pick<Task, 'challenge_duration' | 'submission_deposit'>>
    & { acceptance_criteria: string[] },
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
    if (resp.status === 402) {
      const body = await resp.json().catch(() => null)
      const reason = body?.error || 'payment verification failed'
      throw new Error(`Payment failed: ${reason}`)
    }
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

export async function createChallenge(
  taskId: string,
  data: {
    challenger_submission_id: string
    reason: string
    challenger_wallet?: string
    permit_deadline?: number
    permit_v?: number
    permit_r?: string
    permit_s?: string
  },
): Promise<Challenge> {
  const resp = await fetch(`/api/tasks/${taskId}/challenges`, {
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

export async function judgeChallenge(
  challengeId: string,
  data: { verdict: ChallengeVerdict; score: number; feedback?: string },
): Promise<Challenge> {
  const resp = await fetch(`/api/internal/challenges/${challengeId}/judge`, {
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

export async function submitArbiterVote(
  challengeId: string,
  data: { arbiter_user_id: string; verdict: ArbiterVerdictType; feedback: string },
): Promise<ArbiterVote> {
  const resp = await fetch(`/api/challenges/${challengeId}/vote`, {
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

export async function submitJuryVote(
  taskId: string,
  body: {
    arbiter_user_id: string
    winner_submission_id: string
    malicious_submission_ids: string[]
    feedback: string
  },
): Promise<JuryBallot> {
  const resp = await fetch(`/api/tasks/${taskId}/jury-vote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text)
  }
  return resp.json()
}
