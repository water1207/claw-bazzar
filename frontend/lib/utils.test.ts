import { describe, it, expect } from 'vitest'
import { formatDeadline, formatBounty, scoreColor } from './utils'

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

describe('formatBounty', () => {
  it('returns em dash for null bounty', () => {
    expect(formatBounty(null)).toBe('—')
  })

  it('formats zero bounty', () => {
    expect(formatBounty(0)).toBe('$0.00')
  })

  it('formats whole number bounty', () => {
    expect(formatBounty(10)).toBe('$10.00')
  })

  it('formats decimal bounty', () => {
    expect(formatBounty(5.5)).toBe('$5.50')
  })

  it('formats bounty with many decimals to 2 places', () => {
    expect(formatBounty(1.999)).toBe('$2.00')
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
    // threshold=0.8, 75% = 0.6. Score 0.3 < 0.6
    expect(scoreColor(0.3, 0.8)).toBe('text-red-400')
  })

  it('returns green when no threshold is set', () => {
    expect(scoreColor(0.5, null)).toBe('text-green-400')
  })
})
