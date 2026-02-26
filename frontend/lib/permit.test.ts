import { describe, it, expect } from 'vitest'
import { signChallengePermit, signStakingPermit } from './permit'

const TEST_KEY = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80' as const

describe('signChallengePermit', () => {
  it('returns valid permit signature fields', async () => {
    const result = await signChallengePermit({
      privateKey: TEST_KEY,
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

describe('signStakingPermit', () => {
  it('throws when NEXT_PUBLIC_STAKING_CONTRACT_ADDRESS is not set', async () => {
    delete process.env.NEXT_PUBLIC_STAKING_CONTRACT_ADDRESS
    await expect(signStakingPermit({ privateKey: TEST_KEY, amount: 100 }))
      .rejects.toThrow('NEXT_PUBLIC_STAKING_CONTRACT_ADDRESS not set')
  })

  it('returns valid permit when env var is set', async () => {
    process.env.NEXT_PUBLIC_STAKING_CONTRACT_ADDRESS = '0x1234567890abcdef1234567890abcdef12345678'
    const result = await signStakingPermit({ privateKey: TEST_KEY, amount: 100 })

    expect(result).toHaveProperty('v')
    expect(result).toHaveProperty('r')
    expect(result).toHaveProperty('s')
    expect(result).toHaveProperty('deadline')
    expect(typeof result.v).toBe('number')
    expect(result.r).toMatch(/^0x[0-9a-f]{64}$/)
    expect(result.s).toMatch(/^0x[0-9a-f]{64}$/)

    delete process.env.NEXT_PUBLIC_STAKING_CONTRACT_ADDRESS
  })
})
