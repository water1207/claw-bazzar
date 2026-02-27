// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { buildCandidatePool } from '../ArbiterPanel'
import type { TaskDetail, Challenge } from '@/lib/api'

/* ── Unit tests for buildCandidatePool + mutual exclusion logic ── */

function makeTask(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    id: 'task-1',
    title: 'Test Task',
    description: 'desc',
    type: 'quality_first',
    threshold: null,
    max_revisions: null,
    deadline: '2026-12-31T00:00:00Z',
    status: 'arbitrating',
    winner_submission_id: 'sub-pw',
    created_at: '2026-01-01T00:00:00Z',
    publisher_id: 'pub-1',
    bounty: 10,
    payment_tx_hash: null,
    payout_status: null,
    payout_tx_hash: null,
    payout_amount: null,
    submission_deposit: null,
    challenge_duration: null,
    acceptance_criteria: ['criteria 1'],
    escrow_tx_hash: null,
    scoring_dimensions: [],
    submissions: [
      {
        id: 'sub-pw',
        task_id: 'task-1',
        worker_id: 'worker-pw-id',
        revision: 1,
        content: 'PW content',
        score: 85.5,
        oracle_feedback: null,
        status: 'scored',
        created_at: '2026-01-02T00:00:00Z',
      },
      {
        id: 'sub-ch1',
        task_id: 'task-1',
        worker_id: 'worker-ch1-id',
        revision: 1,
        content: 'Challenger 1 content',
        score: 90.0,
        oracle_feedback: null,
        status: 'scored',
        created_at: '2026-01-03T00:00:00Z',
      },
      {
        id: 'sub-ch2',
        task_id: 'task-1',
        worker_id: 'worker-ch2-id',
        revision: 1,
        content: 'Challenger 2 content',
        score: 70.0,
        oracle_feedback: null,
        status: 'scored',
        created_at: '2026-01-04T00:00:00Z',
      },
    ],
    ...overrides,
  }
}

function makeChallenges(): Challenge[] {
  return [
    {
      id: 'ch-1',
      task_id: 'task-1',
      challenger_submission_id: 'sub-ch1',
      target_submission_id: 'sub-pw',
      reason: 'Better quality',
      verdict: null,
      arbiter_feedback: null,
      arbiter_score: null,
      status: 'pending',
      challenger_wallet: null,
      deposit_tx_hash: null,
      created_at: '2026-01-05T00:00:00Z',
    },
    {
      id: 'ch-2',
      task_id: 'task-1',
      challenger_submission_id: 'sub-ch2',
      target_submission_id: 'sub-pw',
      reason: 'Plagiarism',
      verdict: null,
      arbiter_feedback: null,
      arbiter_score: null,
      status: 'pending',
      challenger_wallet: null,
      deposit_tx_hash: null,
      created_at: '2026-01-06T00:00:00Z',
    },
  ]
}

describe('buildCandidatePool', () => {
  it('includes PW as the first candidate with isPW=true', () => {
    const task = makeTask()
    const challenges = makeChallenges()
    const pool = buildCandidatePool(task, challenges)

    expect(pool.length).toBe(3)
    expect(pool[0].id).toBe('sub-pw')
    expect(pool[0].isPW).toBe(true)
    expect(pool[0].label).toContain('PW:')
  })

  it('includes challengers from challenges', () => {
    const task = makeTask()
    const challenges = makeChallenges()
    const pool = buildCandidatePool(task, challenges)

    const challengers = pool.filter((c) => !c.isPW)
    expect(challengers.length).toBe(2)
    expect(challengers.map((c) => c.id)).toEqual(['sub-ch1', 'sub-ch2'])
    challengers.forEach((c) => {
      expect(c.isPW).toBe(false)
      expect(c.label).toContain('Challenger:')
    })
  })

  it('deduplicates multiple challenges from the same challenger', () => {
    const task = makeTask()
    const challenges = [
      ...makeChallenges(),
      {
        id: 'ch-3',
        task_id: 'task-1',
        challenger_submission_id: 'sub-ch1', // duplicate
        target_submission_id: 'sub-pw',
        reason: 'Another reason',
        verdict: null,
        arbiter_feedback: null,
        arbiter_score: null,
        status: 'pending' as const,
        challenger_wallet: null,
        deposit_tx_hash: null,
        created_at: '2026-01-07T00:00:00Z',
      },
    ]
    const pool = buildCandidatePool(task, challenges)
    // sub-ch1 should appear only once
    expect(pool.filter((c) => c.id === 'sub-ch1').length).toBe(1)
    expect(pool.length).toBe(3)
  })

  it('handles missing PW gracefully (no winner_submission_id)', () => {
    const task = makeTask({ winner_submission_id: null })
    const challenges = makeChallenges()
    const pool = buildCandidatePool(task, challenges)
    // No PW entry
    expect(pool.filter((c) => c.isPW).length).toBe(0)
    expect(pool.length).toBe(2)
  })

  it('handles challenger submission not found in task.submissions', () => {
    const task = makeTask()
    const challenges: Challenge[] = [
      {
        id: 'ch-unknown',
        task_id: 'task-1',
        challenger_submission_id: 'unknown-sub-id',
        target_submission_id: 'sub-pw',
        reason: 'test',
        verdict: null,
        arbiter_feedback: null,
        arbiter_score: null,
        status: 'pending',
        challenger_wallet: null,
        deposit_tx_hash: null,
        created_at: '2026-01-05T00:00:00Z',
      },
    ]
    const pool = buildCandidatePool(task, challenges)
    expect(pool.length).toBe(2)
    const unknown = pool.find((c) => c.id === 'unknown-sub-id')
    expect(unknown).toBeDefined()
    expect(unknown!.label).toContain('Challenger:')
    expect(unknown!.label).toContain('unknown-')
  })
})

describe('Mutual exclusion logic', () => {
  it('selecting a winner removes them from the malicious set', () => {
    // Simulate the state logic from MergedVoteCard
    let winnerId = ''
    let maliciousIds = new Set<string>()

    // First, mark sub-ch1 as malicious
    maliciousIds = new Set([...maliciousIds, 'sub-ch1'])
    expect(maliciousIds.has('sub-ch1')).toBe(true)

    // Then select sub-ch1 as winner - this should remove them from malicious
    winnerId = 'sub-ch1'
    if (maliciousIds.has(winnerId)) {
      const next = new Set(maliciousIds)
      next.delete(winnerId)
      maliciousIds = next
    }

    expect(winnerId).toBe('sub-ch1')
    expect(maliciousIds.has('sub-ch1')).toBe(false)
  })

  it('cannot tag the current winner as malicious', () => {
    const winnerId = 'sub-pw'
    let maliciousIds = new Set<string>()

    // Try to toggle malicious for the winner - should be a no-op
    const subId = 'sub-pw'
    if (subId !== winnerId) {
      const next = new Set(maliciousIds)
      next.add(subId)
      maliciousIds = next
    }

    expect(maliciousIds.has('sub-pw')).toBe(false)
  })

  it('can tag non-winner candidates as malicious', () => {
    const winnerId = 'sub-pw'
    let maliciousIds = new Set<string>()

    // Tag sub-ch1 as malicious - should work since sub-ch1 is not the winner
    const subId = 'sub-ch1'
    if (subId !== winnerId) {
      const next = new Set(maliciousIds)
      next.add(subId)
      maliciousIds = next
    }

    expect(maliciousIds.has('sub-ch1')).toBe(true)
  })

  it('toggling malicious off for a non-winner candidate works', () => {
    const winnerId = 'sub-pw'
    let maliciousIds = new Set<string>(['sub-ch1', 'sub-ch2'])

    // Toggle sub-ch1 off
    const subId = 'sub-ch1'
    if (subId !== winnerId) {
      const next = new Set(maliciousIds)
      if (next.has(subId)) {
        next.delete(subId)
      } else {
        next.add(subId)
      }
      maliciousIds = next
    }

    expect(maliciousIds.has('sub-ch1')).toBe(false)
    expect(maliciousIds.has('sub-ch2')).toBe(true)
  })
})
