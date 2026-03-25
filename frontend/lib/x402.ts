import { Keypair, Connection, Transaction, PublicKey } from '@solana/web3.js'
import { createTransferCheckedInstruction, getAssociatedTokenAddress } from '@solana/spl-token'

const USDC_MINT = new PublicKey('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')
const SOLANA_RPC = 'https://api.devnet.solana.com'
const X402_VERSION = 1

export function getDevWalletAddress(secretKeyBase64: string): string {
  const secret = Buffer.from(secretKeyBase64, 'base64')
  const keypair = Keypair.fromSecretKey(secret)
  return keypair.publicKey.toBase58()
}

export async function signX402Payment(params: {
  secretKey: string  // base64 encoded 64-byte secret key
  payTo: string      // Solana pubkey (Base58)
  amount: number     // USDC amount
}): Promise<string> {
  const { secretKey, payTo, amount } = params
  const keypair = Keypair.fromSecretKey(Buffer.from(secretKey, 'base64'))
  const connection = new Connection(SOLANA_RPC)
  const amountLamports = Math.round(amount * 1e6)

  const fromAta = await getAssociatedTokenAddress(USDC_MINT, keypair.publicKey)
  const toAta = await getAssociatedTokenAddress(USDC_MINT, new PublicKey(payTo))

  const tx = new Transaction().add(
    createTransferCheckedInstruction(
      fromAta, USDC_MINT, toAta,
      keypair.publicKey, amountLamports, 6,
    )
  )

  const { blockhash } = await connection.getLatestBlockhash()
  tx.recentBlockhash = blockhash
  tx.feePayer = keypair.publicKey
  tx.sign(keypair)

  const serialized = tx.serialize()
  const amountStr = amountLamports.toString()

  const paymentPayload = {
    x402Version: X402_VERSION,
    resource: {
      url: 'task-creation',
      description: 'Task creation payment',
      mimeType: 'application/json',
    },
    accepted: {
      scheme: 'exact',
      network: 'solana-devnet',
      asset: USDC_MINT.toBase58(),
      amount: amountStr,
      payTo,
      maxTimeoutSeconds: 30,
    },
    payload: {
      serializedTransaction: Buffer.from(serialized).toString('base64'),
    },
  }

  return btoa(JSON.stringify(paymentPayload))
}
