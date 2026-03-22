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
import { StakingVault } from "../../target/types/staking_vault";

describe("staking-vault", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace.StakingVault as Program<StakingVault>;
  const authority = provider.wallet as anchor.Wallet;

  let usdcMint: anchor.web3.PublicKey;
  let vaultAuthority: anchor.web3.PublicKey;
  let vaultTokenAccount: anchor.web3.PublicKey;
  let configPda: anchor.web3.PublicKey;

  const user = anchor.web3.Keypair.generate();
  let userAta: anchor.web3.PublicKey;
  let authorityAta: anchor.web3.PublicKey;
  let platformAta: anchor.web3.PublicKey;

  before(async () => {
    // Airdrop SOL
    const sig = await provider.connection.requestAirdrop(
      user.publicKey,
      2 * anchor.web3.LAMPORTS_PER_SOL
    );
    await provider.connection.confirmTransaction(sig);

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
      [Buffer.from("vault_authority")],
      program.programId
    );
    [vaultTokenAccount] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("vault_token")],
      program.programId
    );

    // Create ATAs
    userAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      user.publicKey
    );
    authorityAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      authority.publicKey
    );
    platformAta = await createAccount(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      authority.publicKey
    );

    // Mint USDC to user
    await mintTo(
      provider.connection,
      (authority as any).payer,
      usdcMint,
      userAta,
      authority.publicKey,
      50_000_000 // 50 USDC
    );
  });

  it("initializes the staking vault", async () => {
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

  it("stakes USDC", async () => {
    const stakeAmount = 5_000_000; // 5 USDC

    const [stakeRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("stake"), user.publicKey.toBuffer()],
      program.programId
    );

    await program.methods
      .stake(new anchor.BN(stakeAmount))
      .accounts({
        user: user.publicKey,
        config: configPda,
        usdcMint,
        stakeRecord,
        userTokenAccount: userAta,
        vaultTokenAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([user])
      .rpc();

    const record = await program.account.stakeRecord.fetch(stakeRecord);
    assert.equal(record.amount.toNumber(), stakeAmount);
    assert.ok(record.stakedAt.toNumber() > 0);

    // Verify vault balance
    const vaultAccount = await getAccount(provider.connection, vaultTokenAccount);
    assert.equal(Number(vaultAccount.amount), stakeAmount);
  });

  it("stakes additional USDC (accumulates)", async () => {
    const additionalAmount = 3_000_000; // 3 USDC

    const [stakeRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("stake"), user.publicKey.toBuffer()],
      program.programId
    );

    await program.methods
      .stake(new anchor.BN(additionalAmount))
      .accounts({
        user: user.publicKey,
        config: configPda,
        usdcMint,
        stakeRecord,
        userTokenAccount: userAta,
        vaultTokenAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([user])
      .rpc();

    const record = await program.account.stakeRecord.fetch(stakeRecord);
    assert.equal(record.amount.toNumber(), 8_000_000); // 5 + 3
  });

  it("unstakes USDC (authority-controlled)", async () => {
    const unstakeAmount = 2_000_000; // 2 USDC

    const [stakeRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("stake"), user.publicKey.toBuffer()],
      program.programId
    );

    await program.methods
      .unstake(new anchor.BN(unstakeAmount))
      .accounts({
        authority: authority.publicKey,
        config: configPda,
        user: user.publicKey,
        stakeRecord,
        vaultAuthority,
        vaultTokenAccount,
        userTokenAccount: userAta,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .rpc();

    const record = await program.account.stakeRecord.fetch(stakeRecord);
    assert.equal(record.amount.toNumber(), 6_000_000); // 8 - 2
  });

  it("slashes user stake", async () => {
    const [stakeRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("stake"), user.publicKey.toBuffer()],
      program.programId
    );

    const beforeSlash = await program.account.stakeRecord.fetch(stakeRecord);
    const slashAmount = beforeSlash.amount.toNumber();

    await program.methods
      .slash()
      .accounts({
        authority: authority.publicKey,
        config: configPda,
        user: user.publicKey,
        stakeRecord,
        vaultAuthority,
        vaultTokenAccount,
        platformTokenAccount: platformAta,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .rpc();

    const record = await program.account.stakeRecord.fetch(stakeRecord);
    assert.equal(record.amount.toNumber(), 0);

    // Platform received slashed funds
    const platAccount = await getAccount(provider.connection, platformAta);
    assert.equal(Number(platAccount.amount), slashAmount);
  });

  it("rejects zero-amount stake", async () => {
    const [stakeRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("stake"), user.publicKey.toBuffer()],
      program.programId
    );

    try {
      await program.methods
        .stake(new anchor.BN(0))
        .accounts({
          user: user.publicKey,
          config: configPda,
          usdcMint,
          stakeRecord,
          userTokenAccount: userAta,
          vaultTokenAccount,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: anchor.web3.SystemProgram.programId,
        })
        .signers([user])
        .rpc();
      assert.fail("Should have thrown");
    } catch (err: any) {
      assert.include(err.toString(), "AmountZero");
    }
  });

  it("rejects unstake exceeding balance", async () => {
    const [stakeRecord] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("stake"), user.publicKey.toBuffer()],
      program.programId
    );

    try {
      await program.methods
        .unstake(new anchor.BN(999_000_000))
        .accounts({
          authority: authority.publicKey,
          config: configPda,
          user: user.publicKey,
          stakeRecord,
          vaultAuthority,
          vaultTokenAccount,
          userTokenAccount: userAta,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .rpc();
      assert.fail("Should have thrown");
    } catch (err: any) {
      assert.include(err.toString(), "InsufficientStake");
    }
  });
});
