import os
from typing import Optional
from sqlalchemy.orm import Session
from ..models import Task, Submission, User, PayoutStatus

from .solana_utils import (
    get_client,
    get_platform_keypair,
    get_associated_token_address,
    usdc_to_lamports,
    USDC_MINT,
)
from solders.pubkey import Pubkey
from solders.message import Message
from solders.transaction import Transaction
from spl.token.instructions import (
    transfer_checked,
    TransferCheckedParams,
    create_associated_token_account,
)
from spl.token.constants import TOKEN_PROGRAM_ID

PLATFORM_FEE_RATE = float(os.environ.get("PLATFORM_FEE_RATE", "0.20"))

# USDC has 6 decimals
USDC_DECIMALS = 6


def _send_usdc_transfer(to_address: str, amount: float) -> str:
    """Send USDC SPL Token transfer on Solana. Returns tx signature string. Separated for mocking."""
    client = get_client()
    platform_keypair = get_platform_keypair()
    platform_pubkey = platform_keypair.pubkey()

    recipient_pubkey = Pubkey.from_string(to_address)

    sender_ata = get_associated_token_address(platform_pubkey, USDC_MINT)
    recipient_ata = get_associated_token_address(recipient_pubkey, USDC_MINT)

    # Check if recipient ATA exists; create it if not
    instructions = []
    account_info = client.get_account_info(recipient_ata)
    if account_info.value is None:
        create_ata_ix = create_associated_token_account(
            payer=platform_pubkey,
            owner=recipient_pubkey,
            mint=USDC_MINT,
        )
        instructions.append(create_ata_ix)

    # Build transfer_checked instruction
    transfer_ix = transfer_checked(
        TransferCheckedParams(
            program_id=TOKEN_PROGRAM_ID,
            source=sender_ata,
            mint=USDC_MINT,
            dest=recipient_ata,
            owner=platform_pubkey,
            amount=usdc_to_lamports(amount),
            decimals=USDC_DECIMALS,
        )
    )
    instructions.append(transfer_ix)

    # Get recent blockhash and build transaction
    recent_blockhash_resp = client.get_latest_blockhash()
    recent_blockhash = recent_blockhash_resp.value.blockhash

    message = Message(instructions, platform_pubkey)
    tx = Transaction([platform_keypair], message, recent_blockhash)

    # Send and confirm transaction
    resp = client.send_transaction(tx)
    return str(resp.value)


def refund_publisher(db: Session, task_id: str, rate: float = 1.0) -> None:
    """Refund the publisher. rate=1.0 for full refund, 0.95 for 95% refund."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return
    if task.payout_status in (PayoutStatus.paid, PayoutStatus.refunded):
        return

    publisher = db.query(User).filter(User.id == task.publisher_id).first()
    if not publisher:
        return

    refund_amount = round(task.bounty * rate, 6)

    try:
        tx_hash = _send_usdc_transfer(publisher.wallet, refund_amount)
        task.payout_status = PayoutStatus.refunded
        task.refund_amount = refund_amount
        task.refund_tx_hash = tx_hash
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[payout] Refund failed for task {task_id}: {e}", flush=True)

    db.commit()


def pay_winner(db: Session, task_id: str) -> None:
    """Pay the winner of a task. Call after task is closed and winner is set."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not task.winner_submission_id or not task.bounty:
        return
    if task.payout_status == PayoutStatus.paid:
        return

    submission = (
        db.query(Submission).filter(Submission.id == task.winner_submission_id).first()
    )
    if not submission:
        return

    winner = db.query(User).filter(User.id == submission.worker_id).first()
    if not winner:
        return

    from .trust import get_winner_payout_rate

    try:
        rate = get_winner_payout_rate(winner.trust_tier)
    except ValueError:
        rate = 1 - PLATFORM_FEE_RATE
    payout_amount = round(task.bounty * rate, 6)

    try:
        tx_hash = _send_usdc_transfer(winner.wallet, payout_amount)
        task.payout_status = PayoutStatus.paid
        task.payout_tx_hash = tx_hash
        task.payout_amount = payout_amount
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[payout] Failed for task {task_id}: {e}", flush=True)

    db.commit()
