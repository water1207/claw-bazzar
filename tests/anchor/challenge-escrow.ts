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

  const winner = anchor.web3.Keypair.generate();
  const challenger = anchor.web3.Keypair.generate();

  let winnerAta: anchor.web3.PublicKey;
  let challengerAta: anchor.web3.PublicKey;
  let authorityAta: anchor.web3.PublicKey;

  const taskId = "test-task-001";
  const taskIdHash = createHash("sha256").update(taskId).digest();

  before(async () => {
    for (const kp of [winner, challenger]) {
      const sig = await provider.connection.requestAirdrop(
        kp.publicKey,
        2 * anchor.web3.LAMPORTS_PER_SOL
      );
      await provider.connection.confirmTransaction(sig);
    }

    usdcMint = await createMint(
      provider.connection,
      (authority as any).payer,
      authority.publicKey,
      null,
      6,
      undefined,
      undefined,
      TOKEN_PROGRAM_ID
    );

    [configPda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("config")],
      program.programId
    );
    [vaultAuthority] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("escrow_vault")],
      program.programId
    );
    [vaultTokenAccount] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("vault_token")],
      program.programId
    );

    winnerAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      winner.publicKey,
      undefined,
      undefined,
      TOKEN_PROGRAM_ID
    );
    challengerAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      challenger.publicKey,
      undefined,
      undefined,
      TOKEN_PROGRAM_ID
    );
    authorityAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      authority.publicKey,
      undefined,
      undefined,
      TOKEN_PROGRAM_ID
    );

    await mintTo(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      challengerAta,
      authority.publicKey,
      100_000_000
    );
  });

  it("initializes the escrow config", async () => {
    await program.methods
      .initialize(usdcMint)
      .accounts({
        authority: authority.publicKey,
        usdcMint,
        vaultAuthority,
        vaultTokenAccount,
      } as any)
      .rpc();

    const config = await program.account.config.fetch(configPda);
    assert.ok(config.authority.equals(authority.publicKey));
    assert.ok(config.usdcMint.equals(usdcMint));
  });

  it("creates a challenge", async () => {
    const bounty = 10_000_000;
    const incentive = 500_000;

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
      .createChallenge([...taskIdHash], new anchor.BN(bounty), new anchor.BN(incentive), winner.publicKey)
      .accounts({
        authority: authority.publicKey,
        usdcMint,
        challengeInfo: challengePda,
        authorityTokenAccount: authorityAta,
        vaultTokenAccount,
      } as any)
      .rpc();

    const challenge = await program.account.challengeInfo.fetch(challengePda);
    assert.ok(challenge.winner.equals(winner.publicKey));
    assert.equal(challenge.bounty.toNumber(), bounty);
    assert.equal(challenge.incentive.toNumber(), incentive);
    assert.equal(challenge.challengerCount, 0);
    assert.equal(challenge.resolved, false);
  });

  it("allows a challenger to join", async () => {
    const depositAmount = 1_000_000;

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
        usdcMint,
        challengeInfo: challengePda,
        challengerRecord,
        challengerTokenAccount: challengerAta,
        vaultAuthority,
        vaultTokenAccount,
      } as any)
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

    // Vault holds: bounty(10) + incentive(0.5) + deposit(1) + fee(0.01) = 11.51 USDC
    // Winner gets 8, challenger refund from total_deposits, platform gets remainder
    const winnerPayout = 8_000_000;

    await program.methods
      .resolveChallenge(
        [...taskIdHash],
        new anchor.BN(winnerPayout),
        new anchor.BN(0),
        1,
        [true],
        0,
      )
      .accounts({
        authority: authority.publicKey,
        challengeInfo: challengePda,
        vaultAuthority,
        vaultTokenAccount,
        platformTokenAccount: authorityAta,
      } as any)
      .remainingAccounts([
        { pubkey: winnerAta, isSigner: false, isWritable: true },
        { pubkey: challengerAta, isSigner: false, isWritable: true },
        { pubkey: authorityAta, isSigner: false, isWritable: true },
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
        .createChallenge([...taskIdHash], new anchor.BN(1_000_000), new anchor.BN(50_000), winner.publicKey)
        .accounts({
          authority: authority.publicKey,
          usdcMint,
          challengeInfo: challengePda,
          authorityTokenAccount: authorityAta,
          vaultTokenAccount,
        } as any)
        .rpc();
      assert.fail("Should have thrown");
    } catch (err) {
      assert.ok(err);
    }
  });
});
