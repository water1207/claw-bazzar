import { privateKeyToAccount } from 'viem/accounts'
import { type Hex, type Address } from 'viem'
import { baseSepolia } from 'viem/chains'

const USDC_CONTRACT: Address = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'
const X402_VERSION = 2

const EIP712_DOMAIN = {
  name: 'USDC',
  version: '2',
  chainId: baseSepolia.id,
  verifyingContract: USDC_CONTRACT,
} as const

const TRANSFER_WITH_AUTHORIZATION_TYPES = {
  TransferWithAuthorization: [
    { name: 'from', type: 'address' },
    { name: 'to', type: 'address' },
    { name: 'value', type: 'uint256' },
    { name: 'validAfter', type: 'uint256' },
    { name: 'validBefore', type: 'uint256' },
    { name: 'nonce', type: 'bytes32' },
  ],
} as const

function randomNonce(): Hex {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return ('0x' + Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('')) as Hex
}

export function getDevWalletAddress(privateKey: Hex): Address {
  return privateKeyToAccount(privateKey).address
}

export async function signX402Payment(params: {
  privateKey: Hex
  payTo: Address
  amount: number
}): Promise<string> {
  const { privateKey, payTo, amount } = params
  const account = privateKeyToAccount(privateKey)
  const value = BigInt(Math.round(amount * 1e6))
  const now = BigInt(Math.floor(Date.now() / 1000))
  const nonce = randomNonce()

  const authorization = {
    from: account.address,
    to: payTo,
    value,
    validAfter: 0n,
    validBefore: now + 3600n,
    nonce,
  }

  const signature = await account.signTypedData({
    domain: EIP712_DOMAIN,
    types: TRANSFER_WITH_AUTHORIZATION_TYPES,
    primaryType: 'TransferWithAuthorization',
    message: authorization,
  })

  const amountStr = value.toString()

  // Full x402 v2 PaymentPayload per spec
  const paymentPayload = {
    x402Version: X402_VERSION,
    resource: {
      url: 'task-creation',
      description: 'Task creation payment',
      mimeType: 'application/json',
    },
    accepted: {
      scheme: 'exact',
      network: 'eip155:84532',
      asset: USDC_CONTRACT,
      amount: amountStr,
      payTo,
      maxTimeoutSeconds: 30,
      extra: {
        assetTransferMethod: 'eip3009',
        name: 'USDC',
        version: '2',
      },
    },
    payload: {
      signature,
      authorization: {
        from: authorization.from,
        to: authorization.to,
        value: amountStr,
        validAfter: '0',
        validBefore: authorization.validBefore.toString(),
        nonce,
      },
    },
  }

  return btoa(JSON.stringify(paymentPayload))
}
