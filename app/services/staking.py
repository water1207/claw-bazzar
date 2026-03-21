import os
import struct
import base64
import logging
from sqlalchemy.orm import Session
from app.models import User, StakeRecord, StakePurpose, TrustTier
from app.services.trust import apply_event, TrustEventType
from app.services.solana_utils import (
    get_client,
    get_platform_keypair,
    get_associated_token_address,
    find_pda,
    build_instruction,
    usdc_to_lamports,
    USDC_MINT,
)
from solders.pubkey import Pubkey
from solders.instruction import AccountMeta
from solders.transaction import Transaction
from solana.rpc.types import TxOpts
from spl.token.constants import TOKEN_PROGRAM_ID

logger = logging.getLogger(__name__)

ARBITER_STAKE_AMOUNT = 100.0  # USDC
STAKING_PROGRAM_ID = Pubkey.from_string(
    os.environ.get("STAKING_PROGRAM_ID", "11111111111111111111111111111111")
)


def stake_onchain(signed_transaction: str) -> str:
    """Submit a pre-signed stake transaction. Returns tx signature."""
    client = get_client()
    raw_tx = base64.b64decode(signed_transaction)
    resp = client.send_raw_transaction(raw_tx, opts=TxOpts(skip_confirmation=False))
    return str(resp.value)


def slash_onchain(wallet: str) -> str:
    """Call StakingVault slash instruction. Platform authority signs."""
    client = get_client()
    payer = get_platform_keypair()
    user_pubkey = Pubkey.from_string(wallet)

    config_pda, _ = find_pda([b"config"], STAKING_PROGRAM_ID)
    stake_record_pda, _ = find_pda([b"stake", bytes(user_pubkey)], STAKING_PROGRAM_ID)
    vault_authority_pda, _ = find_pda([b"vault_authority"], STAKING_PROGRAM_ID)
    vault_ata = get_associated_token_address(vault_authority_pda, USDC_MINT)
    platform_ata = get_associated_token_address(payer.pubkey(), USDC_MINT)

    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(config_pda, is_signer=False, is_writable=False),
        AccountMeta(stake_record_pda, is_signer=False, is_writable=True),
        AccountMeta(vault_authority_pda, is_signer=False, is_writable=False),
        AccountMeta(vault_ata, is_signer=False, is_writable=True),
        AccountMeta(platform_ata, is_signer=False, is_writable=True),
        AccountMeta(user_pubkey, is_signer=False, is_writable=False),
        AccountMeta(USDC_MINT, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    ix = build_instruction(STAKING_PROGRAM_ID, "slash", b"", accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    return str(resp.value)


def stake_for_arbiter(
    db: Session,
    user_id: str,
    signed_transaction: str,
) -> StakeRecord:
    """Stake 100 USDC for Arbiter registration."""
    user = db.query(User).filter_by(id=user_id).one()

    if user.trust_tier != TrustTier.S:
        raise ValueError("Must be S-tier to become Arbiter")
    if not user.github_id:
        raise ValueError("Must bind GitHub first")
    if user.is_arbiter:
        raise ValueError("Already an Arbiter")

    tx_hash = stake_onchain(signed_transaction)

    user.staked_amount += ARBITER_STAKE_AMOUNT
    user.is_arbiter = True

    record = StakeRecord(
        user_id=user_id,
        amount=ARBITER_STAKE_AMOUNT,
        purpose=StakePurpose.arbiter_deposit,
        tx_hash=tx_hash,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def stake_for_credit(
    db: Session,
    user_id: str,
    amount: float,
    signed_transaction: str,
) -> StakeRecord:
    """Stake USDC for credit recharge (+50 per $50, cap +100)."""
    user = db.query(User).filter_by(id=user_id).one()

    tx_hash = stake_onchain(signed_transaction)

    user.staked_amount += amount
    apply_event(db, user_id, TrustEventType.stake_bonus, stake_amount=amount)

    record = StakeRecord(
        user_id=user_id,
        amount=amount,
        purpose=StakePurpose.credit_recharge,
        tx_hash=tx_hash,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def check_and_slash(db: Session, user_id: str) -> bool:
    """Check if user should be slashed (score < 300 and has stake)."""
    user = db.query(User).filter_by(id=user_id).one()

    if user.trust_score >= 300 or user.staked_amount <= 0:
        return False

    original_staked = user.staked_amount

    try:
        tx_hash = slash_onchain(user.wallet)
    except Exception as e:
        logger.error(f"Slash on-chain failed for {user_id}: {e}")
        tx_hash = None

    apply_event(db, user_id, TrustEventType.stake_slash)

    record = StakeRecord(
        user_id=user_id,
        amount=original_staked,
        purpose=StakePurpose.arbiter_deposit,
        tx_hash=tx_hash,
        slashed=True,
    )
    db.add(record)

    user.staked_amount = 0.0
    user.stake_bonus = 0.0
    user.is_arbiter = False

    db.commit()
    return True


def unstake(db: Session, user_id: str, amount: float) -> StakeRecord:
    """Unstake USDC from the vault. Platform authority signs unstake instruction."""
    user = db.query(User).filter_by(id=user_id).one()
    if user.staked_amount < amount:
        raise ValueError("Insufficient staked amount")

    client = get_client()
    payer = get_platform_keypair()
    user_pubkey = Pubkey.from_string(user.wallet)

    config_pda, _ = find_pda([b"config"], STAKING_PROGRAM_ID)
    stake_record_pda, _ = find_pda([b"stake", bytes(user_pubkey)], STAKING_PROGRAM_ID)
    vault_authority_pda, _ = find_pda([b"vault_authority"], STAKING_PROGRAM_ID)
    vault_ata = get_associated_token_address(vault_authority_pda, USDC_MINT)
    user_ata = get_associated_token_address(user_pubkey, USDC_MINT)

    amount_lamports = usdc_to_lamports(amount)
    args = struct.pack("<Q", amount_lamports)

    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(config_pda, is_signer=False, is_writable=False),
        AccountMeta(stake_record_pda, is_signer=False, is_writable=True),
        AccountMeta(vault_authority_pda, is_signer=False, is_writable=False),
        AccountMeta(vault_ata, is_signer=False, is_writable=True),
        AccountMeta(user_ata, is_signer=False, is_writable=True),
        AccountMeta(user_pubkey, is_signer=False, is_writable=False),
        AccountMeta(USDC_MINT, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    ix = build_instruction(STAKING_PROGRAM_ID, "unstake", args, accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    tx_hash = str(resp.value)

    user.staked_amount -= amount
    if user.is_arbiter and user.staked_amount < ARBITER_STAKE_AMOUNT:
        user.is_arbiter = False

    record = StakeRecord(
        user_id=user_id,
        amount=amount,
        purpose=StakePurpose.credit_recharge,
        tx_hash=tx_hash,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
