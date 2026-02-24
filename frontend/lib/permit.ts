import { createPublicClient, createWalletClient, http, parseUnits, type Hex } from 'viem'
import { baseSepolia } from 'viem/chains'
import { privateKeyToAccount } from 'viem/accounts'

const USDC_ADDRESS = '0x036CbD53842c5426634e7929541eC2318f3dCF7e' as const

export interface PermitResult {
  v: number
  r: string
  s: string
  deadline: number
  nonce: bigint
}

export async function signChallengePermit(params: {
  privateKey: Hex
  spender: string   // ChallengeEscrow contract address
  amount: number    // USDC amount (deposit + service fee)
}): Promise<PermitResult> {
  const account = privateKeyToAccount(params.privateKey)

  const publicClient = createPublicClient({
    chain: baseSepolia,
    transport: http(),
  })

  const walletClient = createWalletClient({
    account,
    chain: baseSepolia,
    transport: http(),
  })

  // Get current nonce from USDC contract
  let nonce: bigint
  try {
    nonce = await publicClient.readContract({
      address: USDC_ADDRESS,
      abi: [{ name: 'nonces', type: 'function', stateMutability: 'view', inputs: [{ name: 'owner', type: 'address' }], outputs: [{ type: 'uint256' }] }],
      functionName: 'nonces',
      args: [account.address],
    }) as bigint
  } catch {
    nonce = 0n
  }

  const deadline = Math.floor(Date.now() / 1000) + 3600 // 1 hour from now
  const value = parseUnits(params.amount.toString(), 6) // USDC 6 decimals

  const signature = await walletClient.signTypedData({
    domain: {
      name: 'USDC',
      version: '2',
      chainId: 84532,
      verifyingContract: USDC_ADDRESS,
    },
    types: {
      Permit: [
        { name: 'owner', type: 'address' },
        { name: 'spender', type: 'address' },
        { name: 'value', type: 'uint256' },
        { name: 'nonce', type: 'uint256' },
        { name: 'deadline', type: 'uint256' },
      ],
    },
    primaryType: 'Permit',
    message: {
      owner: account.address,
      spender: params.spender as `0x${string}`,
      value,
      nonce,
      deadline: BigInt(deadline),
    },
  })

  // Parse signature into v, r, s
  const r = `0x${signature.slice(2, 66)}`
  const s = `0x${signature.slice(66, 130)}`
  const v = parseInt(signature.slice(130, 132), 16)

  return { v, r, s, deadline, nonce }
}
