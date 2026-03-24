/**
 * Initialize challenge_escrow and staking_vault on devnet.
 * Run: npx ts-node scripts/initialize-programs.ts
 */
import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { TOKEN_PROGRAM_ID } from "@solana/spl-token";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { ChallengeEscrow } from "../target/types/challenge_escrow";
import { StakingVault } from "../target/types/staking_vault";

const DEVNET_USDC_MINT = new anchor.web3.PublicKey(
  "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
);

async function main() {
  // Load platform keypair
  const keypairPath = path.join(os.homedir(), ".config", "solana", "platform.json");
  const keypairData = JSON.parse(fs.readFileSync(keypairPath, "utf8"));
  const platformKeypair = anchor.web3.Keypair.fromSecretKey(
    Uint8Array.from(keypairData)
  );

  const connection = new anchor.web3.Connection(
    "https://api.devnet.solana.com",
    "confirmed"
  );
  const wallet = new anchor.Wallet(platformKeypair);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
    preflightCommitment: "confirmed",
  });
  anchor.setProvider(provider);

  console.log("Platform wallet:", platformKeypair.publicKey.toBase58());
  const balance = await connection.getBalance(platformKeypair.publicKey);
  console.log("Balance:", balance / anchor.web3.LAMPORTS_PER_SOL, "SOL");

  // Load programs
  const escrowIdl = JSON.parse(
    fs.readFileSync("target/idl/challenge_escrow.json", "utf8")
  );
  const stakingIdl = JSON.parse(
    fs.readFileSync("target/idl/staking_vault.json", "utf8")
  );

  const escrowProgram = new Program(
    escrowIdl,
    provider
  ) as Program<ChallengeEscrow>;
  const stakingProgram = new Program(
    stakingIdl,
    provider
  ) as Program<StakingVault>;

  // ── challenge_escrow initialize ──────────────────────────────────────────
  const [escrowConfigPda] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("config")],
    escrowProgram.programId
  );
  const [escrowVaultAuthority] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("escrow_vault")],
    escrowProgram.programId
  );
  const [escrowVaultToken] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("vault_token")],
    escrowProgram.programId
  );

  const escrowConfigInfo = await connection.getAccountInfo(escrowConfigPda);
  if (escrowConfigInfo) {
    console.log("challenge_escrow: already initialized, skipping.");
  } else {
    console.log("Initializing challenge_escrow...");
    const tx = await escrowProgram.methods
      .initialize(DEVNET_USDC_MINT)
      .accounts({
        authority: platformKeypair.publicKey,
        config: escrowConfigPda,
        usdcMint: DEVNET_USDC_MINT,
        vaultAuthority: escrowVaultAuthority,
        vaultTokenAccount: escrowVaultToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
        rent: anchor.web3.SYSVAR_RENT_PUBKEY,
      } as any)
      .signers([platformKeypair])
      .rpc();
    console.log("challenge_escrow initialized! tx:", tx);
  }

  // ── staking_vault initialize ─────────────────────────────────────────────
  const [stakingConfigPda] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("config")],
    stakingProgram.programId
  );
  const [stakingVaultAuthority] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("vault_authority")],
    stakingProgram.programId
  );
  const [stakingVaultToken] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("vault_token")],
    stakingProgram.programId
  );

  const stakingConfigInfo = await connection.getAccountInfo(stakingConfigPda);
  if (stakingConfigInfo) {
    console.log("staking_vault: already initialized, skipping.");
  } else {
    console.log("Initializing staking_vault...");
    const tx = await stakingProgram.methods
      .initialize(DEVNET_USDC_MINT)
      .accounts({
        authority: platformKeypair.publicKey,
        config: stakingConfigPda,
        usdcMint: DEVNET_USDC_MINT,
        vaultAuthority: stakingVaultAuthority,
        vaultTokenAccount: stakingVaultToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
        rent: anchor.web3.SYSVAR_RENT_PUBKEY,
      } as any)
      .signers([platformKeypair])
      .rpc();
    console.log("staking_vault initialized! tx:", tx);
  }

  console.log("\nDone.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
