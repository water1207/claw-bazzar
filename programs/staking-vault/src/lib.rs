use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

declare_id!("2pbugkKEhdPgSWGKeohuYyHoNntTtTMwxHSs3EKxpvbL");

/// 30 days in seconds
pub const EMERGENCY_TIMEOUT: i64 = 30 * 24 * 3600;

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

#[event]
pub struct Staked {
    pub user: Pubkey,
    pub amount: u64,
}

#[event]
pub struct Unstaked {
    pub user: Pubkey,
    pub amount: u64,
}

#[event]
pub struct Slashed {
    pub user: Pubkey,
    pub amount: u64,
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[error_code]
pub enum VaultError {
    #[msg("Amount must be greater than zero")]
    AmountZero,
    #[msg("Insufficient staked amount")]
    InsufficientStake,
    #[msg("Nothing to slash")]
    NothingToSlash,
    #[msg("Nothing to withdraw")]
    NothingToWithdraw,
    #[msg("Too early for emergency withdrawal")]
    TooEarlyForEmergency,
    #[msg("Arithmetic overflow")]
    Overflow,
}

// ---------------------------------------------------------------------------
// Account structs
// ---------------------------------------------------------------------------

/// Global config PDA — seeds = [b"config"]
#[account]
pub struct Config {
    /// Platform authority (signs privileged instructions)
    pub authority: Pubkey,
    /// USDC mint address
    pub usdc_mint: Pubkey,
    /// Vault authority PDA bump (seeds = [b"vault_authority"])
    pub vault_bump: u8,
}

impl Config {
    pub const LEN: usize = 8 + 32 + 32 + 1;
}

/// Per-user stake record PDA — seeds = [b"stake", user_pubkey]
#[account]
pub struct StakeRecord {
    /// Staked USDC amount (in lamports, 6 decimals)
    pub amount: u64,
    /// Unix timestamp when first staked (for emergency timeout)
    pub staked_at: i64,
    /// PDA bump
    pub bump: u8,
}

impl StakeRecord {
    pub const LEN: usize = 8 + 8 + 8 + 1;
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
        seeds = [b"vault_authority"],
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
pub struct Stake<'info> {
    #[account(mut)]
    pub user: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = usdc_mint,
    )]
    pub config: Account<'info, Config>,

    pub usdc_mint: Account<'info, Mint>,

    #[account(
        init_if_needed,
        payer = user,
        space = StakeRecord::LEN,
        seeds = [b"stake", user.key().as_ref()],
        bump,
    )]
    pub stake_record: Account<'info, StakeRecord>,

    /// User's USDC token account (source)
    #[account(
        mut,
        token::mint = usdc_mint,
        token::authority = user,
    )]
    pub user_token_account: Account<'info, TokenAccount>,

    /// Vault token account (destination)
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
pub struct Unstake<'info> {
    /// Authority signs unstake (platform-controlled)
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
    )]
    pub config: Account<'info, Config>,

    /// CHECK: user whose stake is being released
    pub user: UncheckedAccount<'info>,

    #[account(
        mut,
        seeds = [b"stake", user.key().as_ref()],
        bump = stake_record.bump,
    )]
    pub stake_record: Account<'info, StakeRecord>,

    /// CHECK: vault authority PDA
    #[account(
        seeds = [b"vault_authority"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Vault token account (source)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    /// User's USDC token account (destination)
    #[account(mut)]
    pub user_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Slash<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
    )]
    pub config: Account<'info, Config>,

    /// CHECK: user being slashed
    pub user: UncheckedAccount<'info>,

    #[account(
        mut,
        seeds = [b"stake", user.key().as_ref()],
        bump = stake_record.bump,
    )]
    pub stake_record: Account<'info, StakeRecord>,

    /// CHECK: vault authority PDA
    #[account(
        seeds = [b"vault_authority"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Vault token account (source)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    /// Platform token account (receives slashed funds)
    #[account(mut)]
    pub platform_token_account: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct EmergencyWithdraw<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        seeds = [b"config"],
        bump,
        has_one = authority,
    )]
    pub config: Account<'info, Config>,

    /// CHECK: user whose stake is being emergency-withdrawn
    pub user: UncheckedAccount<'info>,

    #[account(
        mut,
        seeds = [b"stake", user.key().as_ref()],
        bump = stake_record.bump,
    )]
    pub stake_record: Account<'info, StakeRecord>,

    /// CHECK: vault authority PDA
    #[account(
        seeds = [b"vault_authority"],
        bump,
    )]
    pub vault_authority: UncheckedAccount<'info>,

    /// Vault token account (source)
    #[account(
        mut,
        seeds = [b"vault_token"],
        bump,
    )]
    pub vault_token_account: Account<'info, TokenAccount>,

    /// Authority token account (receives withdrawn funds)
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
pub mod staking_vault {
    use super::*;

    /// Initialize: store config PDA and create vault token account owned by vault_authority PDA.
    pub fn initialize(ctx: Context<Initialize>, usdc_mint: Pubkey) -> Result<()> {
        let config = &mut ctx.accounts.config;
        config.authority = ctx.accounts.authority.key();
        config.usdc_mint = usdc_mint;
        config.vault_bump = ctx.bumps.vault_authority;
        Ok(())
    }

    /// User stakes USDC: transfers amount from user ATA → vault; creates/updates StakeRecord.
    pub fn stake(ctx: Context<Stake>, amount: u64) -> Result<()> {
        require!(amount > 0, VaultError::AmountZero);

        // Transfer from user → vault
        let cpi_ctx = CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_token_account.to_account_info(),
                to: ctx.accounts.vault_token_account.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        );
        token::transfer(cpi_ctx, amount)?;

        // Update stake record
        let record = &mut ctx.accounts.stake_record;
        if record.staked_at == 0 {
            record.staked_at = Clock::get()?.unix_timestamp;
            record.bump = ctx.bumps.stake_record;
        }
        record.amount = record
            .amount
            .checked_add(amount)
            .ok_or(VaultError::Overflow)?;

        emit!(Staked {
            user: ctx.accounts.user.key(),
            amount,
        });

        Ok(())
    }

    /// Authority unstakes on behalf of user: transfers amount from vault → user ATA.
    pub fn unstake(ctx: Context<Unstake>, amount: u64) -> Result<()> {
        require!(amount > 0, VaultError::AmountZero);
        require!(
            ctx.accounts.stake_record.amount >= amount,
            VaultError::InsufficientStake
        );

        let vault_bump = ctx.accounts.config.vault_bump;
        let vault_seeds: &[&[u8]] = &[b"vault_authority", &[vault_bump]];
        let signer_seeds = &[vault_seeds];

        let cpi_accounts = Transfer {
            from: ctx.accounts.vault_token_account.to_account_info(),
            to: ctx.accounts.user_token_account.to_account_info(),
            authority: ctx.accounts.vault_authority.to_account_info(),
        };
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            cpi_accounts,
            signer_seeds,
        );
        token::transfer(cpi_ctx, amount)?;

        ctx.accounts.stake_record.amount = ctx
            .accounts
            .stake_record
            .amount
            .checked_sub(amount)
            .ok_or(VaultError::Overflow)?;

        emit!(Unstaked {
            user: ctx.accounts.user.key(),
            amount,
        });

        Ok(())
    }

    /// Authority slashes user: transfers full stake from vault → platform ATA; zeroes record.
    pub fn slash(ctx: Context<Slash>) -> Result<()> {
        let amount = ctx.accounts.stake_record.amount;
        require!(amount > 0, VaultError::NothingToSlash);

        let vault_bump = ctx.accounts.config.vault_bump;
        let vault_seeds: &[&[u8]] = &[b"vault_authority", &[vault_bump]];
        let signer_seeds = &[vault_seeds];

        let cpi_accounts = Transfer {
            from: ctx.accounts.vault_token_account.to_account_info(),
            to: ctx.accounts.platform_token_account.to_account_info(),
            authority: ctx.accounts.vault_authority.to_account_info(),
        };
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            cpi_accounts,
            signer_seeds,
        );
        token::transfer(cpi_ctx, amount)?;

        ctx.accounts.stake_record.amount = 0;

        emit!(Slashed {
            user: ctx.accounts.user.key(),
            amount,
        });

        Ok(())
    }

    /// Emergency withdrawal: only callable after EMERGENCY_TIMEOUT since staked_at.
    /// Transfers remaining stake to authority ATA and zeroes the record.
    pub fn emergency_withdraw(ctx: Context<EmergencyWithdraw>) -> Result<()> {
        let record = &ctx.accounts.stake_record;
        let amount = record.amount;
        require!(amount > 0, VaultError::NothingToWithdraw);

        let now = Clock::get()?.unix_timestamp;
        require!(
            now >= record.staked_at + EMERGENCY_TIMEOUT,
            VaultError::TooEarlyForEmergency
        );

        let vault_bump = ctx.accounts.config.vault_bump;
        let vault_seeds: &[&[u8]] = &[b"vault_authority", &[vault_bump]];
        let signer_seeds = &[vault_seeds];

        let cpi_accounts = Transfer {
            from: ctx.accounts.vault_token_account.to_account_info(),
            to: ctx.accounts.authority_token_account.to_account_info(),
            authority: ctx.accounts.vault_authority.to_account_info(),
        };
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            cpi_accounts,
            signer_seeds,
        );
        token::transfer(cpi_ctx, amount)?;

        ctx.accounts.stake_record.amount = 0;

        emit!(Unstaked {
            user: ctx.accounts.user.key(),
            amount,
        });

        Ok(())
    }
}
