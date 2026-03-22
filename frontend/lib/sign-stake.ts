import { Keypair, Connection, Transaction, PublicKey, TransactionInstruction, SystemProgram } from '@solana/web3.js'
import { getAssociatedTokenAddress, TOKEN_PROGRAM_ID } from '@solana/spl-token'

const USDC_MINT = new PublicKey('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')
const SOLANA_RPC = 'https://api.devnet.solana.com'

// Anchor discriminator for stake
const STAKE_DISCRIMINATOR = Buffer.from([206, 176, 202, 18, 200, 209, 179, 108])

export async function signStake(params: {
  secretKey: string         // base64 encoded keypair
  stakingProgramId: string  // program pubkey
  amount: number            // USDC stake amount
}): Promise<string> {
  const { secretKey, stakingProgramId, amount } = params
  const keypair = Keypair.fromSecretKey(Buffer.from(secretKey, 'base64'))
  const connection = new Connection(SOLANA_RPC)
  const programId = new PublicKey(stakingProgramId)

  const amountLamports = Math.round(amount * 1e6)

  // Derive PDAs
  const [configPda] = PublicKey.findProgramAddressSync(
    [Buffer.from('config')],
    programId,
  )
  const [stakeRecord] = PublicKey.findProgramAddressSync(
    [Buffer.from('stake'), keypair.publicKey.toBuffer()],
    programId,
  )
  const [vaultTokenAccount] = PublicKey.findProgramAddressSync(
    [Buffer.from('vault_token')],
    programId,
  )

  const userAta = await getAssociatedTokenAddress(USDC_MINT, keypair.publicKey)

  // Borsh serialize: discriminator(8) + amount(u64)
  const data = Buffer.alloc(8 + 8)
  STAKE_DISCRIMINATOR.copy(data, 0)
  data.writeBigUInt64LE(BigInt(amountLamports), 8)

  const ix = new TransactionInstruction({
    programId,
    keys: [
      { pubkey: keypair.publicKey, isSigner: true, isWritable: true },     // user
      { pubkey: configPda, isSigner: false, isWritable: false },           // config
      { pubkey: USDC_MINT, isSigner: false, isWritable: false },           // usdc_mint
      { pubkey: stakeRecord, isSigner: false, isWritable: true },          // stake_record
      { pubkey: userAta, isSigner: false, isWritable: true },              // user_token_account
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
