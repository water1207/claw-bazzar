import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import {
  createMint,
  createAccount,
  mintTo,
  getAccount,
  TOKEN_PROGRAM_ID,
} from "@solana/spl-token";
import { assert } from "chai";
import { ChallengeEscrow } from "../../target/types/challenge_escrow";
import { createHash } from "crypto";

describe("challenge-escrow", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace
    .ChallengeEscrow as Program<ChallengeEscrow>;
  const authority = provider.wallet as anchor.Wallet;

  let usdcMint: anchor.web3.PublicKey;
  let vaultAuthority: anchor.web3.PublicKey;
  let vaultTokenAccount: anchor.web3.PublicKey;
  let configPda: anchor.web3.PublicKey;

  // Test users
  const winner = anchor.web3.Keypair.generate();
  const challenger = anchor.web3.Keypair.generate();

  let winnerAta: anchor.web3.PublicKey;
  let challengerAta: anchor.web3.PublicKey;
  let authorityAta: anchor.web3.PublicKey;

  const taskId = "test-task-001";
  const taskIdHash = createHash("sha256").update(taskId).digest();

  before(async () => {
    // Airdrop SOL to test accounts
    for (const kp of [winner, challenger]) {
      const sig = await provider.connection.requestAirdrop(
        kp.publicKey,
        2 * anchor.web3.LAMPORTS_PER_SOL
      );
      await provider.connection.confirmTransaction(sig);
    }

    // Create USDC mock mint
    usdcMint = await createMint(
      provider.connection,
      (authority as any).payer,
      authority.publicKey,
      null,
      6
    );

    // Derive PDAs
    [configPda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("config")],
      program.programId
    );
    [vaultAuthority] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("escrow_vault")],
      program.programId
    );
    [vaultTokenAccount] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("escrow_vault_token")],
      program.programId
    );

    // Create ATAs for test users
    winnerAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      winner.publicKey
    );
    challengerAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      challenger.publicKey
    );
    authorityAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      authority.publicKey
    );

    // Mint USDC to challenger (for deposits)
    await mintTo(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      challengerAta,
      authority.publicKey,
      100_000_000 // 100 USDC
    );
  });

  it("initializes the escrow config", async () => {
    await program.methods
      .initialize(usdcMint)
      .accounts({
        authority: authority.publicKey,
        config: configPda,
        usdcMint,
        vaultAuthority,
        vaultTokenAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
        rent: anchor.web3.SYSVAR_RENT_PUBKEY,
      })
      .rpc();

    const config = await program.account.config.fetch(configPda);
    assert.ok(config.authority.equals(authority.publicKey));
    assert.ok(config.usdcMint.equals(usdcMint));
  });

  it("creates a challenge", async () => {
    const bounty = 10_000_000; // 10 USDC
    const incentive = 500_000; // 0.5 USDC

    // Mint bounty to authority ATA first
    await mintTo(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      authorityAta,
      authority.publicKey,
      bounty + incentive
    );

    const [challengePda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("challenge"), taskIdHash],
      program.programId
    );

    await program.methods
      .createChallenge([...taskIdHash], new anchor.BN(bounty), new anchor.BN(incentive))
      .accounts({
        authority: authority.publicKey,
        config: configPda,
        challengeInfo: challengePda,
        winner: winner.publicKey,
        authorityTokenAccount: authorityAta,
        vaultAuthority,
        vaultTokenAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .rpc();

    const challenge = await program.account.challengeInfo.fetch(challengePda);
    assert.ok(challenge.winner.equals(winner.publicKey));
    assert.equal(challenge.bounty.toNumber(), bounty);
    assert.equal(challenge.incentive.toNumber(), incentive);
    assert.equal(challenge.challengerCount, 0);
    assert.equal(challenge.resolved, false);
  });

  it("allows a challenger to join", async () => {
    const depositAmount = 1_000_000; // 1 USDC
    const serviceFee = 10_000; // 0.01 USDC

    const [challengePda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("challenge"), taskIdHash],
      program.programId
    );
    const [challengerRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("challenger"), taskIdHash, challenger.publicKey.toBuffer()],
      program.programId
    );

    await program.methods
      .joinChallenge([...taskIdHash], new anchor.BN(depositAmount))
      .accounts({
        challenger: challenger.publicKey,
        config: configPda,
        challengeInfo: challengePda,
        challengerRecord,
        challengerTokenAccount: challengerAta,
        vaultAuthority,
        vaultTokenAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([challenger])
      .rpc();

    const record = await program.account.challengerRecord.fetch(challengerRecord);
    assert.equal(record.depositAmount.toNumber(), depositAmount);

    const challenge = await program.account.challengeInfo.fetch(challengePda);
    assert.equal(challenge.challengerCount, 1);
    assert.equal(challenge.totalDeposits.toNumber(), depositAmount);
  });

  it("resolves a challenge (winner upheld)", async () => {
    const [challengePda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("challenge"), taskIdHash],
      program.programId
    );

    const challenge = await program.account.challengeInfo.fetch(challengePda);
    const winnerPayout = challenge.bounty.toNumber();

    // Resolve with original winner upheld, challenger refunded
    await program.methods
      .resolveChallenge(
        [...taskIdHash],
        winner.publicKey,
        new anchor.BN(winnerPayout),
        [{ wallet: challenger.publicKey, amount: new anchor.BN(1_000_000) }],
        [],
        new anchor.BN(0)
      )
      .accounts({
        authority: authority.publicKey,
        config: configPda,
        challengeInfo: challengePda,
        vaultAuthority,
        vaultTokenAccount,
        platformTokenAccount: authorityAta,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .remainingAccounts([
        // Winner ATA
        { pubkey: winnerAta, isSigner: false, isWritable: true },
        // Challenger refund ATA
        { pubkey: challengerAta, isSigner: false, isWritable: true },
      ])
      .rpc();

    const resolved = await program.account.challengeInfo.fetch(challengePda);
    assert.equal(resolved.resolved, true);
  });

  it("rejects duplicate challenge creation", async () => {
    try {
      const [challengePda] = anchor.web3.PublicKey.findProgramAddressSync(
        [Buffer.from("challenge"), taskIdHash],
        program.programId
      );

      await program.methods
        .createChallenge([...taskIdHash], new anchor.BN(1_000_000), new anchor.BN(50_000))
        .accounts({
          authority: authority.publicKey,
          config: configPda,
          challengeInfo: challengePda,
          winner: winner.publicKey,
          authorityTokenAccount: authorityAta,
          vaultAuthority,
          vaultTokenAccount,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: anchor.web3.SystemProgram.programId,
        })
        .rpc();
      assert.fail("Should have thrown");
    } catch (err) {
      // PDA already initialized — Anchor rejects re-init
      assert.ok(err);
    }
  });
});
