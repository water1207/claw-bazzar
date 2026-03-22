import { Keypair, Connection, Transaction, PublicKey, SystemProgram } from '@solana/web3.js'
import { createTransferCheckedInstruction, getAssociatedTokenAddress, TOKEN_PROGRAM_ID } from '@solana/spl-token'

const USDC_MINT = new PublicKey('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')
const SOLANA_RPC = 'https://api.devnet.solana.com'
const SERVICE_FEE = 10_000 // 0.01 USDC in lamports

export async function signJoinChallenge(params: {
  secretKey: string       // base64 encoded keypair
  escrowProgramId: string // program pubkey
  taskIdHash: Uint8Array  // 32-byte SHA-256 of task ID
  depositAmount: number   // USDC deposit amount
}): Promise<string> {
  const { secretKey, escrowProgramId, taskIdHash, depositAmount } = params
  const keypair = Keypair.fromSecretKey(Buffer.from(secretKey, 'base64'))
  const connection = new Connection(SOLANA_RPC)
  const programId = new PublicKey(escrowProgramId)

  const depositLamports = Math.round(depositAmount * 1e6)
  const totalAmount = depositLamports + SERVICE_FEE

  // Derive escrow vault PDA
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [Buffer.from('escrow_vault')],
    programId,
  )
  const vaultAta = await getAssociatedTokenAddress(USDC_MINT, vaultPda, true)
  const challengerAta = await getAssociatedTokenAddress(USDC_MINT, keypair.publicKey)

  // Transfer deposit + service fee to vault
  const tx = new Transaction().add(
    createTransferCheckedInstruction(
      challengerAta, USDC_MINT, vaultAta,
      keypair.publicKey, totalAmount, 6,
    )
  )

  const { blockhash } = await connection.getLatestBlockhash()
  tx.recentBlockhash = blockhash
  tx.feePayer = keypair.publicKey
  tx.sign(keypair)

  return Buffer.from(tx.serialize()).toString('base64')
}
