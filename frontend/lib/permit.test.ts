import { describe, it, expect } from 'vitest'
import { signChallengePermit } from './permit'

describe('signChallengePermit', () => {
  it('returns valid permit signature fields', async () => {
    // Use a known test private key
    const testKey = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
    const result = await signChallengePermit({
      privateKey: testKey,
      spender: '0x1234567890abcdef1234567890abcdef12345678',
      amount: 1.01, // 1 USDC deposit + 0.01 service fee
    })

    expect(result).toHaveProperty('v')
    expect(result).toHaveProperty('r')
    expect(result).toHaveProperty('s')
    expect(result).toHaveProperty('deadline')
    expect(typeof result.v).toBe('number')
    expect(result.r).toMatch(/^0x[0-9a-f]{64}$/)
    expect(result.s).toMatch(/^0x[0-9a-f]{64}$/)
    expect(result.deadline).toBeGreaterThan(Math.floor(Date.now() / 1000))
  })
})
