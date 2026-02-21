import { describe, it, expect } from 'vitest'
import { getDevWalletAddress, signX402Payment } from './x402'
import type { Hex } from 'viem'

// Well-known test private key (do NOT use in production)
const TEST_KEY: Hex = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
const TEST_ADDRESS = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'

describe('getDevWalletAddress', () => {
  it('derives correct address from known private key', () => {
    const address = getDevWalletAddress(TEST_KEY)
    expect(address.toLowerCase()).toBe(TEST_ADDRESS.toLowerCase())
  })
})

describe('signX402Payment', () => {
  it('returns base64 with full x402 v2 payload structure', async () => {
    const result = await signX402Payment({
      privateKey: TEST_KEY,
      payTo: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
      amount: 2.5,
    })

    const decoded = JSON.parse(atob(result))
    expect(decoded.x402Version).toBe(2)
    expect(decoded.resource).toHaveProperty('url')
    expect(decoded.accepted).toHaveProperty('scheme', 'exact')
    expect(decoded.accepted).toHaveProperty('amount', '2500000')
    expect(decoded.accepted.extra.assetTransferMethod).toBe('eip3009')
    expect(decoded.payload).toHaveProperty('signature')
    expect(decoded.payload.authorization).toHaveProperty('from')
    expect(decoded.payload.authorization).toHaveProperty('to')
    expect(decoded.payload.authorization).toHaveProperty('value')
    expect(decoded.payload.authorization).toHaveProperty('nonce')
  })

  it('converts amount to USDC micro-units', async () => {
    const result = await signX402Payment({
      privateKey: TEST_KEY,
      payTo: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
      amount: 10,
    })

    const decoded = JSON.parse(atob(result))
    expect(decoded.payload.authorization.value).toBe('10000000')
    expect(decoded.accepted.amount).toBe('10000000')
  })

  it('sets from to the signer address', async () => {
    const result = await signX402Payment({
      privateKey: TEST_KEY,
      payTo: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
      amount: 1,
    })

    const decoded = JSON.parse(atob(result))
    expect(decoded.payload.authorization.from.toLowerCase()).toBe(TEST_ADDRESS.toLowerCase())
  })
})
