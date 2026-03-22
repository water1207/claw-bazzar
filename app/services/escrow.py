"""ChallengeEscrow Anchor program interaction layer."""

import struct
import base64
import os
from .solana_utils import (
    get_client,
    get_platform_keypair,
    get_associated_token_address,
    task_id_to_seed,
    usdc_to_lamports,
    lamports_to_usdc,
    build_instruction,
    find_pda,
    USDC_MINT,
)
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solana.rpc.types import TxOpts
from solders.instruction import AccountMeta
from spl.token.constants import TOKEN_PROGRAM_ID

ESCROW_PROGRAM_ID = Pubkey.from_string(
    os.environ.get("ESCROW_PROGRAM_ID", "11111111111111111111111111111111")
)


def _get_escrow_pdas(task_id: str):
    """Derive all PDAs needed for escrow instructions."""
    task_seed = task_id_to_seed(task_id)
    challenge_pda, challenge_bump = find_pda(
        [b"challenge", task_seed], ESCROW_PROGRAM_ID
    )
    vault_pda, vault_bump = find_pda([b"escrow_vault"], ESCROW_PROGRAM_ID)
    config_pda, _ = find_pda([b"config"], ESCROW_PROGRAM_ID)
    return task_seed, challenge_pda, vault_pda, config_pda


def check_usdc_balance(wallet_address: str) -> float:
    """Check USDC balance of a Solana wallet. Returns amount in USDC."""
    client = get_client()
    owner = Pubkey.from_string(wallet_address)
    ata = get_associated_token_address(owner, USDC_MINT)
    try:
        resp = client.get_token_account_balance(ata)
        if resp.value:
            return float(resp.value.ui_amount or 0)
    except Exception:
        pass
    return 0.0


def create_challenge_onchain(
    task_id: str, winner_wallet: str, bounty: float, incentive: float
) -> str:
    """Call ChallengeEscrow create_challenge instruction."""
    client = get_client()
    payer = get_platform_keypair()
    task_seed, challenge_pda, vault_pda, config_pda = _get_escrow_pdas(task_id)

    bounty_lamports = usdc_to_lamports(bounty)
    incentive_lamports = usdc_to_lamports(incentive)
    winner_pubkey = Pubkey.from_string(winner_wallet)

    # Borsh serialize: task_id_hash(32) + bounty(u64) + incentive(u64) + winner(Pubkey, 32 bytes)
    args = (
        task_seed
        + struct.pack("<QQ", bounty_lamports, incentive_lamports)
        + bytes(winner_pubkey)
    )

    payer_ata = get_associated_token_address(payer.pubkey(), USDC_MINT)

    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),  # authority
        AccountMeta(config_pda, is_signer=False, is_writable=False),  # config
        AccountMeta(USDC_MINT, is_signer=False, is_writable=False),  # usdc_mint
        AccountMeta(challenge_pda, is_signer=False, is_writable=True),  # challenge_info
        AccountMeta(
            payer_ata, is_signer=False, is_writable=True
        ),  # authority_token_account
        AccountMeta(
            vault_pda, is_signer=False, is_writable=True
        ),  # vault_token_account
        AccountMeta(
            TOKEN_PROGRAM_ID, is_signer=False, is_writable=False
        ),  # token_program
        AccountMeta(
            Pubkey.from_string("11111111111111111111111111111111"),
            is_signer=False,
            is_writable=False,
        ),  # system_program
    ]

    ix = build_instruction(ESCROW_PROGRAM_ID, "create_challenge", args, accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    sig = str(resp.value)
    print(f"[escrow] createChallenge({task_id}) tx={sig}", flush=True)
    return sig


def join_challenge_onchain(task_id: str, signed_transaction: str) -> str:
    """Submit a pre-signed join_challenge transaction to the network."""
    client = get_client()
    raw_tx = base64.b64decode(signed_transaction)
    resp = client.send_raw_transaction(raw_tx, opts=TxOpts(skip_confirmation=False))
    sig = str(resp.value)
    print(f"[escrow] joinChallenge({task_id}) tx={sig}", flush=True)
    return sig


def resolve_challenge_onchain(
    task_id: str,
    final_winner_wallet: str,
    winner_payout: float,
    refunds: list[dict],
    arbiter_wallets: list[str],
    arbiter_reward: float,
) -> str:
    """Call ChallengeEscrow resolve_challenge instruction with remaining accounts."""
    client = get_client()
    payer = get_platform_keypair()
    task_seed, challenge_pda, vault_pda, config_pda = _get_escrow_pdas(task_id)

    winner_pubkey = Pubkey.from_string(final_winner_wallet)
    winner_payout_lamports = usdc_to_lamports(winner_payout)
    arbiter_reward_lamports = usdc_to_lamports(arbiter_reward)
    num_refunds = len(refunds)
    num_arbiters = len(arbiter_wallets)

    # Borsh: task_id_hash(32) + winner_payout(u64) + arbiter_reward(u64) + num_refunds(u32) + refund_flags(bool[]) + num_arbiters(u32)
    args = task_seed
    args += struct.pack("<QQ", winner_payout_lamports, arbiter_reward_lamports)
    args += struct.pack("<I", num_refunds)
    for r in refunds:
        args += struct.pack("<?", r["refund"])
    args += struct.pack("<I", num_arbiters)

    vault_authority_pda, _ = find_pda([b"escrow_vault"], ESCROW_PROGRAM_ID)

    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),  # authority
        AccountMeta(config_pda, is_signer=False, is_writable=False),  # config
        AccountMeta(challenge_pda, is_signer=False, is_writable=True),  # challenge_info
        AccountMeta(
            vault_authority_pda, is_signer=False, is_writable=False
        ),  # vault_authority
        AccountMeta(
            vault_pda, is_signer=False, is_writable=True
        ),  # vault_token_account
        AccountMeta(
            TOKEN_PROGRAM_ID, is_signer=False, is_writable=False
        ),  # token_program
    ]

    # Remaining accounts: winner ATA, then refund ATAs, then arbiter ATAs, then platform ATA
    winner_ata = get_associated_token_address(winner_pubkey, USDC_MINT)
    accounts.append(AccountMeta(winner_ata, is_signer=False, is_writable=True))

    for r in refunds:
        challenger_pubkey = Pubkey.from_string(r["challenger"])
        challenger_ata = get_associated_token_address(challenger_pubkey, USDC_MINT)
        accounts.append(AccountMeta(challenger_ata, is_signer=False, is_writable=True))

    for a in arbiter_wallets:
        arbiter_pubkey = Pubkey.from_string(a)
        arbiter_ata = get_associated_token_address(arbiter_pubkey, USDC_MINT)
        accounts.append(AccountMeta(arbiter_ata, is_signer=False, is_writable=True))

    # Platform ATA (last remaining account — receives vault remainder)
    platform_ata = get_associated_token_address(payer.pubkey(), USDC_MINT)
    accounts.append(AccountMeta(platform_ata, is_signer=False, is_writable=True))

    ix = build_instruction(ESCROW_PROGRAM_ID, "resolve_challenge", args, accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    sig = str(resp.value)
    print(f"[escrow] resolveChallenge({task_id}) tx={sig}", flush=True)
    return sig


def void_challenge_onchain(
    task_id: str,
    publisher_wallet: str,
    publisher_refund: float,
    refunds: list[dict],
    arbiter_wallets: list[str],
    arbiter_reward: float,
) -> str:
    """Call ChallengeEscrow void_challenge instruction."""
    client = get_client()
    payer = get_platform_keypair()
    task_seed, challenge_pda, vault_pda, config_pda = _get_escrow_pdas(task_id)

    publisher_pubkey = Pubkey.from_string(publisher_wallet)
    publisher_refund_lamports = usdc_to_lamports(publisher_refund)
    arbiter_reward_lamports = usdc_to_lamports(arbiter_reward)
    num_refunds = len(refunds)
    num_arbiters = len(arbiter_wallets)

    args = task_seed
    args += struct.pack("<QQ", publisher_refund_lamports, arbiter_reward_lamports)
    args += struct.pack("<I", num_refunds)
    for r in refunds:
        args += struct.pack("<?", r["refund"])
    args += struct.pack("<I", num_arbiters)

    vault_authority_pda, _ = find_pda([b"escrow_vault"], ESCROW_PROGRAM_ID)

    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),  # authority
        AccountMeta(config_pda, is_signer=False, is_writable=False),  # config
        AccountMeta(challenge_pda, is_signer=False, is_writable=True),  # challenge_info
        AccountMeta(
            vault_authority_pda, is_signer=False, is_writable=False
        ),  # vault_authority
        AccountMeta(
            vault_pda, is_signer=False, is_writable=True
        ),  # vault_token_account
        AccountMeta(
            TOKEN_PROGRAM_ID, is_signer=False, is_writable=False
        ),  # token_program
    ]

    # Remaining accounts: publisher ATA, refund ATAs, arbiter ATAs, platform ATA
    publisher_ata = get_associated_token_address(publisher_pubkey, USDC_MINT)
    accounts.append(AccountMeta(publisher_ata, is_signer=False, is_writable=True))

    for r in refunds:
        challenger_pubkey = Pubkey.from_string(r["challenger"])
        challenger_ata = get_associated_token_address(challenger_pubkey, USDC_MINT)
        accounts.append(AccountMeta(challenger_ata, is_signer=False, is_writable=True))

    for a in arbiter_wallets:
        arbiter_pubkey = Pubkey.from_string(a)
        arbiter_ata = get_associated_token_address(arbiter_pubkey, USDC_MINT)
        accounts.append(AccountMeta(arbiter_ata, is_signer=False, is_writable=True))

    # Platform ATA (last remaining account — receives vault remainder)
    platform_ata = get_associated_token_address(payer.pubkey(), USDC_MINT)
    accounts.append(AccountMeta(platform_ata, is_signer=False, is_writable=True))

    ix = build_instruction(ESCROW_PROGRAM_ID, "void_challenge", args, accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    sig = str(resp.value)
    print(f"[escrow] voidChallenge({task_id}) tx={sig}", flush=True)
    return sig
