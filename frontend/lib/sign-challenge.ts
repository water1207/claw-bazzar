import { Keypair, Connection, Transaction, PublicKey, TransactionInstruction, SystemProgram } from '@solana/web3.js'
import { getAssociatedTokenAddress, TOKEN_PROGRAM_ID } from '@solana/spl-token'
import { createHash } from 'crypto'

const USDC_MINT = new PublicKey('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')
const SOLANA_RPC = 'https://api.devnet.solana.com'

// Anchor discriminator for join_challenge
const JOIN_CHALLENGE_DISCRIMINATOR = Buffer.from([41, 104, 214, 73, 32, 168, 76, 79])

export async function signJoinChallenge(params: {
  secretKey: string       // base64 encoded keypair
  escrowProgramId: string // program pubkey
  taskIdHash: Uint8Array  // 32-byte SHA-256 of task ID
  depositAmount: number   // USDC deposit amount (in USDC, not lamports)
}): Promise<string> {
  const { secretKey, escrowProgramId, taskIdHash, depositAmount } = params
  const keypair = Keypair.fromSecretKey(Buffer.from(secretKey, 'base64'))
  const connection = new Connection(SOLANA_RPC)
  const programId = new PublicKey(escrowProgramId)

  const depositLamports = Math.round(depositAmount * 1e6)

  // Derive PDAs
  const [configPda] = PublicKey.findProgramAddressSync(
    [Buffer.from('config')],
    programId,
  )
  const [challengePda] = PublicKey.findProgramAddressSync(
    [Buffer.from('challenge'), Buffer.from(taskIdHash)],
    programId,
  )
  const [challengerRecord] = PublicKey.findProgramAddressSync(
    [Buffer.from('challenger'), Buffer.from(taskIdHash), keypair.publicKey.toBuffer()],
    programId,
  )
  const [vaultTokenAccount] = PublicKey.findProgramAddressSync(
    [Buffer.from('vault_token')],
    programId,
  )

  // Fetch config to get usdc_mint
  const challengerAta = await getAssociatedTokenAddress(USDC_MINT, keypair.publicKey)

  // Borsh serialize: discriminator(8) + task_id_hash(32) + deposit_amount(u64)
  const data = Buffer.alloc(8 + 32 + 8)
  JOIN_CHALLENGE_DISCRIMINATOR.copy(data, 0)
  Buffer.from(taskIdHash).copy(data, 8)
  data.writeBigUInt64LE(BigInt(depositLamports), 40)

  const ix = new TransactionInstruction({
    programId,
    keys: [
      { pubkey: keypair.publicKey, isSigner: true, isWritable: true },     // challenger
      { pubkey: configPda, isSigner: false, isWritable: false },           // config
      { pubkey: USDC_MINT, isSigner: false, isWritable: false },           // usdc_mint
      { pubkey: challengePda, isSigner: false, isWritable: true },         // challenge_info
      { pubkey: challengerRecord, isSigner: false, isWritable: true },     // challenger_record
      { pubkey: challengerAta, isSigner: false, isWritable: true },        // challenger_token_account
      { pubkey: vaultTokenAccount, isSigner: false, isWritable: true },    // vault_token_account
      { pubkey: TOKEN_PROGRAM_ID, isSigner: false, isWritable: false },    // token_program
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false }, // system_program
    ],
    data,
  })

  const tx = new Transaction().add(ix)
  const { blockhash } = await connection.getLatestBlockhash()
  tx.recentBlockhash = blockhash
  tx.feePayer = keypair.publicKey
  tx.sign(keypair)

  return Buffer.from(tx.serialize()).toString('base64')
}
