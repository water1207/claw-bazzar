import os
import logging
from sqlalchemy.orm import Session
from app.models import User, StakeRecord, StakePurpose, TrustTier
from app.services.trust import apply_event, TrustEventType

logger = logging.getLogger(__name__)

ARBITER_STAKE_AMOUNT = 100.0  # USDC


def stake_onchain(wallet: str, amount: float, deadline: int,
                  v: int, r: str, s: str) -> str:
    """Call StakingVault.stake() on-chain. Returns tx hash."""
    from web3 import Web3
    rpc = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract_addr = os.environ.get("STAKING_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("PLATFORM_PRIVATE_KEY", "")

    abi = [{
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "name": "stake",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }]

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    amount_wei = int(amount * 1e6)
    account = w3.eth.account.from_key(private_key)

    tx = contract.functions.stake(
        wallet, amount_wei, deadline, v,
        bytes.fromhex(r[2:]) if r.startswith("0x") else bytes.fromhex(r),
        bytes.fromhex(s[2:]) if s.startswith("0x") else bytes.fromhex(s),
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 200000,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def slash_onchain(wallet: str) -> str:
    """Call StakingVault.slash() on-chain. Returns tx hash."""
    from web3 import Web3
    rpc = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract_addr = os.environ.get("STAKING_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("PLATFORM_PRIVATE_KEY", "")

    abi = [{
        "inputs": [{"name": "user", "type": "address"}],
        "name": "slash",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }]

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    account = w3.eth.account.from_key(private_key)

    tx = contract.functions.slash(wallet).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 200000,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def stake_for_arbiter(
    db: Session, user_id: str,
    deadline: int, v: int, r: str, s: str,
) -> StakeRecord:
    """Stake 100 USDC for Arbiter registration."""
    user = db.query(User).filter_by(id=user_id).one()

    if user.trust_tier != TrustTier.S:
        raise ValueError("Must be S-tier to become Arbiter")
    if not user.github_id:
        raise ValueError("Must bind GitHub first")
    if user.is_arbiter:
        raise ValueError("Already an Arbiter")

    tx_hash = stake_onchain(user.wallet, ARBITER_STAKE_AMOUNT,
                            deadline, v, r, s)

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
    db: Session, user_id: str, amount: float,
    deadline: int, v: int, r: str, s: str,
) -> StakeRecord:
    """Stake USDC for credit recharge (+50 per $50, cap +100)."""
    user = db.query(User).filter_by(id=user_id).one()

    tx_hash = stake_onchain(user.wallet, amount, deadline, v, r, s)

    user.staked_amount += amount

    # Apply stake bonus via TrustService
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

    # Capture original staked amount before apply_event zeroes it
    original_staked = user.staked_amount

    try:
        tx_hash = slash_onchain(user.wallet)
    except Exception as e:
        logger.error(f"Slash on-chain failed for {user_id}: {e}")
        tx_hash = None

    # Apply stake_slash event (removes stake_bonus)
    apply_event(db, user_id, TrustEventType.stake_slash)

    # Record the slash
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
    """Unstake USDC from the vault."""
    user = db.query(User).filter_by(id=user_id).one()
    if user.staked_amount < amount:
        raise ValueError("Insufficient staked amount")

    from web3 import Web3
    rpc = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract_addr = os.environ.get("STAKING_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("PLATFORM_PRIVATE_KEY", "")

    abi = [{
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "unstake",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }]

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    amount_wei = int(amount * 1e6)
    account = w3.eth.account.from_key(private_key)

    tx = contract.functions.unstake(user.wallet, amount_wei).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 200000,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    user.staked_amount -= amount
    if user.is_arbiter and user.staked_amount < ARBITER_STAKE_AMOUNT:
        user.is_arbiter = False

    record = StakeRecord(
        user_id=user_id,
        amount=amount,
        purpose=StakePurpose.credit_recharge,
        tx_hash=tx_hash.hex(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
