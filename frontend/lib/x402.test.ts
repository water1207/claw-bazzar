import { describe, it, expect } from 'vitest'
import { getDevWalletAddress } from './x402'
import { Keypair } from '@solana/web3.js'

const TEST_KEYPAIR = Keypair.generate()
const TEST_SECRET_BASE64 = Buffer.from(TEST_KEYPAIR.secretKey).toString('base64')

describe('x402 Solana', () => {
  it('getDevWalletAddress returns Base58 pubkey', () => {
    const address = getDevWalletAddress(TEST_SECRET_BASE64)
    expect(address).toBeTruthy()
    expect(address.length).toBeGreaterThanOrEqual(32)
    expect(address.length).toBeLessThanOrEqual(44)
  })
})
