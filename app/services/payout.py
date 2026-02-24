import os
from typing import Optional
from web3 import Web3
from sqlalchemy.orm import Session
from ..models import Task, Submission, User, PayoutStatus

PLATFORM_PRIVATE_KEY = os.environ.get("PLATFORM_PRIVATE_KEY", "")
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "")
RPC_URL = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
PLATFORM_FEE_RATE = float(os.environ.get("PLATFORM_FEE_RATE", "0.20"))

# Minimal ERC-20 ABI for transfer
ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    }
]


def _send_usdc_transfer(to_address: str, amount: float) -> str:
    """Send USDC transfer on-chain. Returns tx hash. Separated for mocking."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT), abi=ERC20_TRANSFER_ABI
    )
    # USDC has 6 decimals
    amount_wei = int(amount * 10**6)
    account = w3.eth.account.from_key(PLATFORM_PRIVATE_KEY)
    tx = contract.functions.transfer(
        Web3.to_checksum_address(to_address), amount_wei
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    return tx_hash.hex()


def refund_publisher(db: Session, task_id: str, rate: float = 1.0) -> None:
    """Refund the publisher. rate=1.0 for full refund, 0.95 for 95% refund."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not task.bounty or task.bounty <= 0:
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

    submission = db.query(Submission).filter(
        Submission.id == task.winner_submission_id
    ).first()
    if not submission:
        return

    winner = db.query(User).filter(User.id == submission.worker_id).first()
    if not winner:
        return

    payout_amount = round(task.bounty * (1 - PLATFORM_FEE_RATE), 6)

    try:
        tx_hash = _send_usdc_transfer(winner.wallet, payout_amount)
        task.payout_status = PayoutStatus.paid
        task.payout_tx_hash = tx_hash
        task.payout_amount = payout_amount
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[payout] Failed for task {task_id}: {e}", flush=True)

    db.commit()
