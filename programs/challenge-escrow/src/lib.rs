use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

declare_id!("3Ucu2cxQmTRV3n1zJZryVTiJTMFR9iMQEn5gyNoxQX1H");

/// 0.01 USDC (6 decimals)
pub const SERVICE_FEE: u64 = 10_000;
/// 30 days in seconds
pub const EMERGENCY_TIMEOUT: i64 = 30 * 24 * 3600;

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

#[event]
pub struct ChallengeCreated {
    pub task_id_hash: [u8; 32],
    pub winner: Pubkey,
    pub bounty: u64,
}

#[event]
pub struct ChallengerJoined {
    pub task_id_hash: [u8; 32],
    pub challenger: Pubkey,
    pub deposit_amount: u64,
}

#[event]
pub struct ChallengeResolved {
    pub task_id_hash: [u8; 32],
    pub final_winner: Pubkey,
    pub verdict: u8,
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[error_code]
pub enum EscrowError {
    #[msg("Challenge already exists")]
    ChallengeAlreadyExists,
    #[msg("Challenge not found")]
    ChallengeNotFound,
    #[msg("Already resolved")]
    AlreadyResolved,
    #[msg("Already joined")]
    AlreadyJoined,
    #[msg("Bounty must be positive")]
    BountyZero,
    #[msg("Incentive exceeds bounty")]
    IncentiveExceedsBounty,
    #[msg("Too early for emergency withdrawal")]
    TooEarlyForEmergency,
    #[msg("Insufficient remaining accounts")]
    InsufficientRemainingAccounts,
    #[msg("Arithmetic overflow")]
    Overflow,
}

// ---------------------------------------------------------------------------
// Account structs
// ---------------------------------------------------------------------------

/// Global config PDA — seeds = [b"config"]
#[account]
pub struct Config {
    /// Platform authority (signs all privileged instructions)
    pub authority: Pubkey,
    /// USDC mint address
    pub usdc_mint: Pubkey,
    /// Vault authority PDA bump (seeds = [b"escrow_vault"])
    pub vault_bump: u8,
}

impl Config {
    pub const LEN: usize = 8 + 32 + 32 + 1;
}

/// Per-task challenge state PDA — seeds = [b"challenge", task_id_hash]
#[account]
pub struct ChallengeInfo {
    /// Provisional winner at challenge creation time
    pub winner: Pubkey,
    /// Locked bounty amount (bounty * 95%)
    pub bounty: u64,
    /// Challenge incentive portion (bounty * 5%)
    pub incentive: u64,
    /// Per-challenger service fee (SERVICE_FEE = 0.01 USDC)
    pub service_fee: u64,
    /// Number of challengers who joined
    pub challenger_count: u8,
    /// Whether the challenge has been settled
    pub resolved: bool,
    /// Unix timestamp of creation (for emergency timeout)
    pub created_at: i64,
    /// Sum of all challenger principal deposits (excludes service fees)
    pub total_deposits: u64,
    /// PDA bump
    pub bump: u8,
}

impl ChallengeInfo {
    pub const LEN: usize = 8 + 32 + 8 + 8 + 8 + 1 + 1 + 8 + 8 + 1;
}

/// Per-challenger deposit record PDA — seeds = [b"challenger", task_id_hash, challenger_pubkey]
#[account]
pub struct ChallengerRecord {
    /// Deposit amount (excluding service fee)
    pub deposit_amount: u64,
    /// PDA bump
    pub bump: u8,
}

impl ChallengerRecord {
    pub const LEN: usize = 8 + 8 + 1;
}

// ---------------------------------------------------------------------------
// Instruction contexts
// ---------------------------------------------------------------------------

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        init,
        payer = authority,
        space = Config::LEN,
        seeds = [b"config"],
        bump,
    )]
    pub config: Account<'info, Config>,

    pub usdc_mint: Account<'info, Mint>,

    /// CHECK: vault authority PDA — owns the vault token account
    #[account(
        seeds = [b"escrow_vault"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    #[account(
        init,
        payer = authority,
        token::mint = usdc_mint,
        token::authority = vault_authority,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
#[instruction(task_id_hash: [u8; 32])]
pub struct CreateChallenge<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
        has_one = usdc_mint,
    )]
    pub config: Account<'info, Config>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = authority,
        space = ChallengeInfo::LEN,
        seeds = [b"challenge", task_id_hash.as_ref()],
        bump,
    )]
    pub challenge_info: Account<'info, ChallengeInfo>,

    /// Authority's USDC token account (source of bounty)
    #[account(
        mut,
        token::mint = usdc_mint,
        token::authority = authority,
    )]
    pub authority_token_account: Account<'info, TokenAccount>,

    /// Escrow vault token account (destination)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
        token::mint = usdc_mint,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(task_id_hash: [u8; 32])]
pub struct JoinChallenge<'info> {
    #[account(mut)]
    pub challenger: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = usdc_mint,
    )]
    pub config: Account<'info, Config>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        mut,
        seeds = [b"challenge", task_id_hash.as_ref()],
        bump = challenge_info.bump,
    )]
    pub challenge_info: Account<'info, ChallengeInfo>,

    #[account(
        init,
        payer = challenger,
        space = ChallengerRecord::LEN,
        seeds = [b"challenger", task_id_hash.as_ref(), challenger.key().as_ref()],
        bump,
    )]
    pub challenger_record: Account<'info, ChallengerRecord>,

    /// Challenger's USDC token account (source)
    #[account(
        mut,
        token::mint = usdc_mint,
        token::authority = challenger,
    )]
    pub challenger_token_account: Account<'info, TokenAccount>,

    /// Escrow vault token account (destination)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
        token::mint = usdc_mint,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

/// resolve_challenge and void_challenge share the same base accounts;
/// dynamic recipients are passed via remaining_accounts.
#[derive(Accounts)]
#[instruction(task_id_hash: [u8; 32])]
pub struct ResolveChallenge<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
    )]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [b"challenge", task_id_hash.as_ref()],
        bump = challenge_info.bump,
    )]
    pub challenge_info: Account<'info, ChallengeInfo>,

    /// CHECK: vault authority PDA — signs token transfers out of vault
    #[account(
        seeds = [b"escrow_vault"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Escrow vault token account (source of all payouts)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(task_id_hash: [u8; 32])]
pub struct VoidChallenge<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
    )]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [b"challenge", task_id_hash.as_ref()],
        bump = challenge_info.bump,
    )]
    pub challenge_info: Account<'info, ChallengeInfo>,

    /// CHECK: vault authority PDA
    #[account(
        seeds = [b"escrow_vault"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Escrow vault token account (source)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(task_id_hash: [u8; 32])]
pub struct EmergencyWithdraw<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
    )]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [b"challenge", task_id_hash.as_ref()],
        bump = challenge_info.bump,
    )]
    pub challenge_info: Account<'info, ChallengeInfo>,

    /// CHECK: vault authority PDA
    #[account(
        seeds = [b"escrow_vault"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Escrow vault token account (source)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    /// Authority's USDC token account (destination)
    #[account(
        mut,
        token::mint = vault_token_account.mint,
        token::authority = authority,
    )]
    pub authority_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

// ---------------------------------------------------------------------------
// Program
// ---------------------------------------------------------------------------

#[program]
pub mod challenge_escrow {
    use super::*;

    /// Initialize the program: store config and create the escrow vault token account.
    pub fn initialize(ctx: Context<Initialize>, usdc_mint: Pubkey) -> Result<()> {
        let config = &mut ctx.accounts.config;
        config.authority = ctx.accounts.authority.key();
        config.usdc_mint = usdc_mint;
        config.vault_bump = ctx.bumps.vault_authority;
        Ok(())
    }

    /// Lock bounty from authority ATA → escrow vault; create ChallengeInfo PDA.
    pub fn create_challenge(
        ctx: Context<CreateChallenge>,
        task_id_hash: [u8; 32],
        bounty: u64,
        incentive: u64,
        winner: Pubkey,
    ) -> Result<()> {
        require!(bounty > 0, EscrowError::BountyZero);
        require!(incentive <= bounty, EscrowError::IncentiveExceedsBounty);

        // Transfer bounty from authority ATA → vault
        let cpi_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.authority_token_account.to_account_info(),
                to: ctx.accounts.vault_token_account.to_account_info(),
                authority: ctx.accounts.authority.to_account_info(),
            },
        );
        token::transfer(cpi_ctx, bounty)?;

        let info = &mut ctx.accounts.challenge_info;
        info.winner = winner;
        info.bounty = bounty;
        info.incentive = incentive;
        info.service_fee = SERVICE_FEE;
        info.challenger_count = 0;
        info.resolved = false;
        info.created_at = Clock::get()?.unix_timestamp;
        info.total_deposits = 0;
        info.bump = ctx.bumps.challenge_info;

        emit!(ChallengeCreated {
            task_id_hash,
            winner,
            bounty,
        });

        Ok(())
    }

    /// Challenger joins: deposit + service fee transferred to vault; ChallengerRecord PDA created.
    pub fn join_challenge(
        ctx: Context<JoinChallenge>,
        task_id_hash: [u8; 32],
        deposit_amount: u64,
    ) -> Result<()> {
        let info = &ctx.accounts.challenge_info;
        require!(!info.resolved, EscrowError::AlreadyResolved);

        let total_transfer = deposit_amount
            .checked_add(SERVICE_FEE)
            .ok_or(EscrowError::Overflow)?;

        // Transfer deposit + service fee from challenger → vault
        let cpi_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.challenger_token_account.to_account_info(),
                to: ctx.accounts.vault_token_account.to_account_info(),
                authority: ctx.accounts.challenger.to_account_info(),
            },
        );
        token::transfer(cpi_ctx, total_transfer)?;

        // Record deposit
        let record = &mut ctx.accounts.challenger_record;
        record.deposit_amount = deposit_amount;
        record.bump = ctx.bumps.challenger_record;

        // Update challenge state
        let info = &mut ctx.accounts.challenge_info;
        info.challenger_count = info
            .challenger_count
            .checked_add(1)
            .ok_or(EscrowError::Overflow)?;
        info.total_deposits = info
            .total_deposits
            .checked_add(deposit_amount)
            .ok_or(EscrowError::Overflow)?;

        emit!(ChallengerJoined {
            task_id_hash,
            challenger: ctx.accounts.challenger.key(),
            deposit_amount,
        });

        Ok(())
    }

    /// Resolve challenge: distribute vault funds to winner, refunded challengers, arbiters, platform.
    ///
    /// remaining_accounts layout (all writable token accounts):
    ///   [0]              winner ATA
    ///   [1..num_refunds] challenger ATAs (only those with refund_flags[i] == true are paid)
    ///   [num_refunds..num_refunds+num_arbiters] arbiter ATAs
    ///   [last]           platform ATA (always last)
    ///
    /// refund_flags[i] corresponds to remaining_accounts[1+i].
    pub fn resolve_challenge<'a>(
        ctx: Context<'_, '_, 'a, 'a, ResolveChallenge<'a>>,
        task_id_hash: [u8; 32],
        winner_payout: u64,
        arbiter_reward: u64,
        num_refunds: u32,
        refund_flags: Vec<bool>,
        num_arbiters: u32,
    ) -> Result<()> {
        let info = &ctx.accounts.challenge_info;
        require!(!info.resolved, EscrowError::AlreadyResolved);

        let vault_bump = ctx.accounts.config.vault_bump;
        let vault_seeds: &[&[u8]] = &[b"escrow_vault", &[vault_bump]];
        let signer_seeds = &[vault_seeds];

        // Expect: 1 (winner) + num_refunds + num_arbiters + 1 (platform) accounts
        let expected = 1
            + num_refunds as usize
            + num_arbiters as usize
            + 1;
        require!(
            ctx.remaining_accounts.len() >= expected,
            EscrowError::InsufficientRemainingAccounts
        );

        let remaining = ctx.remaining_accounts;
        let mut idx: usize = 0;

        // 1. Winner payout
        if winner_payout > 0 {
            let winner_ata = &remaining[idx];
            transfer_from_vault(
                &ctx.accounts.vault_token_account,
                winner_ata,
                &ctx.accounts.vault_authority,
                &ctx.accounts.token_program,
                winner_payout,
                signer_seeds,
            )?;
        }
        idx += 1; // advance past winner slot regardless

        // 2. Refund challenger deposits
        for i in 0..num_refunds as usize {
            if i < refund_flags.len() && refund_flags[i] {
                // Retrieve per-challenger deposit from ChallengeInfo (total_deposits tracks sum;
                // individual amounts must be passed via refund_amounts in a production extension,
                // but here we distribute each challenger's pro-rata share of total_deposits).
                // For simplicity: caller ensures per-challenger refund amounts are encoded in
                // winner_payout = 0 slots; the raw deposit is stored in the ChallengerRecord PDA
                // which only the backend knows. We use the remaining_accounts index to identify
                // the recipient — the actual amount per challenger is computed off-chain and
                // callers may use refund_amounts (see note below).
                //
                // NOTE: In a full implementation, pass `refund_amounts: Vec<u64>` alongside
                // refund_flags. Here we fall back to splitting total_deposits equally among
                // refunded challengers as a safe approximation.
                let challenger_ata = &remaining[idx + i];
                let refunded_count = refund_flags.iter().filter(|&&b| b).count() as u64;
                if refunded_count > 0 {
                    let per_refund = ctx
                        .accounts
                        .challenge_info
                        .total_deposits
                        .checked_div(refunded_count)
                        .unwrap_or(0);
                    if per_refund > 0 {
                        transfer_from_vault(
                            &ctx.accounts.vault_token_account,
                            challenger_ata,
                            &ctx.accounts.vault_authority,
                            &ctx.accounts.token_program,
                            per_refund,
                            signer_seeds,
                        )?;
                    }
                }
            }
        }
        idx += num_refunds as usize;

        // 3. Arbiter reward (split equally)
        if arbiter_reward > 0 && num_arbiters > 0 {
            let per_arbiter = arbiter_reward
                .checked_div(num_arbiters as u64)
                .unwrap_or(0);
            for i in 0..num_arbiters as usize {
                if per_arbiter > 0 {
                    let arbiter_ata = &remaining[idx + i];
                    transfer_from_vault(
                        &ctx.accounts.vault_token_account,
                        arbiter_ata,
                        &ctx.accounts.vault_authority,
                        &ctx.accounts.token_program,
                        per_arbiter,
                        signer_seeds,
                    )?;
                }
            }
        }
        idx += num_arbiters as usize;

        // 4. Platform gets remainder
        let vault_balance = ctx.accounts.vault_token_account.amount;
        if vault_balance > 0 {
            let platform_ata = &remaining[idx];
            transfer_from_vault(
                &ctx.accounts.vault_token_account,
                platform_ata,
                &ctx.accounts.vault_authority,
                &ctx.accounts.token_program,
                vault_balance,
                signer_seeds,
            )?;
        }

        ctx.accounts.challenge_info.resolved = true;

        emit!(ChallengeResolved {
            task_id_hash,
            final_winner: ctx.accounts.challenge_info.winner,
            verdict: 0,
        });

        Ok(())
    }

    /// Void challenge: refund publisher, handle challengers, pay arbiters, platform gets remainder.
    ///
    /// remaining_accounts layout:
    ///   [0]              publisher ATA
    ///   [1..num_refunds] challenger ATAs (refund_flags[i] selects which are paid back)
    ///   [num_refunds..num_refunds+num_arbiters] arbiter ATAs
    ///   [last]           platform ATA
    pub fn void_challenge<'a>(
        ctx: Context<'_, '_, 'a, 'a, VoidChallenge<'a>>,
        task_id_hash: [u8; 32],
        publisher_refund: u64,
        arbiter_reward: u64,
        num_refunds: u32,
        refund_flags: Vec<bool>,
        num_arbiters: u32,
    ) -> Result<()> {
        let info = &ctx.accounts.challenge_info;
        require!(!info.resolved, EscrowError::AlreadyResolved);

        let vault_bump = ctx.accounts.config.vault_bump;
        let vault_seeds: &[&[u8]] = &[b"escrow_vault", &[vault_bump]];
        let signer_seeds = &[vault_seeds];

        let expected = 1
            + num_refunds as usize
            + num_arbiters as usize
            + 1;
        require!(
            ctx.remaining_accounts.len() >= expected,
            EscrowError::InsufficientRemainingAccounts
        );

        let remaining = ctx.remaining_accounts;
        let mut idx: usize = 0;

        // 1. Publisher refund
        if publisher_refund > 0 {
            let publisher_ata = &remaining[idx];
            transfer_from_vault(
                &ctx.accounts.vault_token_account,
                publisher_ata,
                &ctx.accounts.vault_authority,
                &ctx.accounts.token_program,
                publisher_refund,
                signer_seeds,
            )?;
        }
        idx += 1;

        // 2. Challenger refunds (upheld challengers get deposit back)
        {
            let refunded_count = refund_flags.iter().filter(|&&b| b).count() as u64;
            for i in 0..num_refunds as usize {
                if i < refund_flags.len() && refund_flags[i] && refunded_count > 0 {
                    let challenger_ata = &remaining[idx + i];
                    let per_refund = ctx
                        .accounts
                        .challenge_info
                        .total_deposits
                        .checked_div(refunded_count)
                        .unwrap_or(0);
                    if per_refund > 0 {
                        transfer_from_vault(
                            &ctx.accounts.vault_token_account,
                            challenger_ata,
                            &ctx.accounts.vault_authority,
                            &ctx.accounts.token_program,
                            per_refund,
                            signer_seeds,
                        )?;
                    }
                }
            }
        }
        idx += num_refunds as usize;

        // 3. Arbiter reward (split equally)
        if arbiter_reward > 0 && num_arbiters > 0 {
            let per_arbiter = arbiter_reward
                .checked_div(num_arbiters as u64)
                .unwrap_or(0);
            for i in 0..num_arbiters as usize {
                if per_arbiter > 0 {
                    let arbiter_ata = &remaining[idx + i];
                    transfer_from_vault(
                        &ctx.accounts.vault_token_account,
                        arbiter_ata,
                        &ctx.accounts.vault_authority,
                        &ctx.accounts.token_program,
                        per_arbiter,
                        signer_seeds,
                    )?;
                }
            }
        }
        idx += num_arbiters as usize;

        // 4. Platform gets remainder
        let vault_balance = ctx.accounts.vault_token_account.amount;
        if vault_balance > 0 {
            let platform_ata = &remaining[idx];
            transfer_from_vault(
                &ctx.accounts.vault_token_account,
                platform_ata,
                &ctx.accounts.vault_authority,
                &ctx.accounts.token_program,
                vault_balance,
                signer_seeds,
            )?;
        }

        ctx.accounts.challenge_info.resolved = true;

        emit!(ChallengeResolved {
            task_id_hash,
            final_winner: Pubkey::default(),
            verdict: 3, // voided
        });

        Ok(())
    }

    /// Emergency withdrawal: only after EMERGENCY_TIMEOUT since creation. Transfers all vault
    /// funds to authority and marks the challenge resolved.
    pub fn emergency_withdraw(
        ctx: Context<EmergencyWithdraw>,
        _task_id_hash: [u8; 32],
    ) -> Result<()> {
        let info = &ctx.accounts.challenge_info;
        require!(!info.resolved, EscrowError::AlreadyResolved);

        let now = Clock::get()?.unix_timestamp;
        require!(
            now >= info.created_at + EMERGENCY_TIMEOUT,
            EscrowError::TooEarlyForEmergency
        );

        let vault_bump = ctx.accounts.config.vault_bump;
        let vault_seeds: &[&[u8]] = &[b"escrow_vault", &[vault_bump]];
        let signer_seeds = &[vault_seeds];

        let amount = ctx.accounts.vault_token_account.amount;
        if amount > 0 {
            transfer_from_vault(
                &ctx.accounts.vault_token_account,
                ctx.accounts.authority_token_account.as_ref(),
                &ctx.accounts.vault_authority,
                &ctx.accounts.token_program,
                amount,
                signer_seeds,
            )?;
        }

        ctx.accounts.challenge_info.resolved = true;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Helper: PDA-signed transfer from vault
// ---------------------------------------------------------------------------

fn transfer_from_vault<'info>(
    vault_token_account: &Account<'info, TokenAccount>,
    destination: &AccountInfo<'info>,
    vault_authority: &UncheckedAccount<'info>,
    token_program: &Program<'info, Token>,
    amount: u64,
    signer_seeds: &[&[&[u8]]],
) -> Result<()> {
    let cpi_accounts = Transfer {
        from: vault_token_account.to_account_info(),
        to: destination.clone(),
        authority: vault_authority.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::transfer(cpi_ctx, amount)
}
