import { Keypair, Connection, Transaction, PublicKey } from '@solana/web3.js'
import { createTransferCheckedInstruction, getAssociatedTokenAddress } from '@solana/spl-token'

const USDC_MINT = new PublicKey('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')
const SOLANA_RPC = 'https://api.devnet.solana.com'

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

  // Derive vault authority PDA
  const [vaultAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from('vault_authority')],
    programId,
  )
  const vaultAta = await getAssociatedTokenAddress(USDC_MINT, vaultAuthority, true)
  const userAta = await getAssociatedTokenAddress(USDC_MINT, keypair.publicKey)

  const tx = new Transaction().add(
    createTransferCheckedInstruction(
      userAta, USDC_MINT, vaultAta,
      keypair.publicKey, amountLamports, 6,
    )
  )

  const { blockhash } = await connection.getLatestBlockhash()
  tx.recentBlockhash = blockhash
  tx.feePayer = keypair.publicKey
  tx.sign(keypair)

  return Buffer.from(tx.serialize()).toString('base64')
}
