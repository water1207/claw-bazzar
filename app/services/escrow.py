"""ChallengeEscrow contract interaction layer."""
import json
import os
from pathlib import Path
from web3 import Web3

PLATFORM_PRIVATE_KEY = os.environ.get("PLATFORM_PRIVATE_KEY", "")
RPC_URL = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS", "")

# Minimal ERC-20 ABI for balanceOf
ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    }
]


def _load_escrow_abi() -> list:
    """Load ChallengeEscrow ABI from Foundry output."""
    abi_path = Path(__file__).parent.parent.parent / "contracts" / "out" / "ChallengeEscrow.sol" / "ChallengeEscrow.json"
    if abi_path.exists():
        with open(abi_path, encoding="utf-8") as f:
            return json.load(f)["abi"]
    # Fallback: minimal ABI for the 4 functions we use
    return _MINIMAL_ESCROW_ABI


# Minimal ABI fallback (used when Foundry artifacts not available, e.g. in tests)
_MINIMAL_ESCROW_ABI = [
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "winner_", "type": "address"},
            {"name": "bounty", "type": "uint256"},
            {"name": "incentive", "type": "uint256"},
        ],
        "name": "createChallenge",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "challenger", "type": "address"},
            {"name": "depositAmount", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "name": "joinChallenge",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "finalWinner", "type": "address"},
            {"name": "winnerPayout", "type": "uint256"},
            {
                "name": "verdicts",
                "type": "tuple[]",
                "components": [
                    {"name": "challenger", "type": "address"},
                    {"name": "result", "type": "uint8"},
                    {"name": "arbiters", "type": "address[]"},
                ],
            },
        ],
        "name": "resolveChallenge",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [{"name": "taskId", "type": "bytes32"}],
        "name": "emergencyWithdraw",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "publisher", "type": "address"},
            {"name": "publisherRefund", "type": "uint256"},
            {
                "name": "refunds",
                "type": "tuple[]",
                "components": [
                    {"name": "challenger", "type": "address"},
                    {"name": "refund", "type": "bool"},
                ],
            },
            {"name": "arbiters", "type": "address[]"},
            {"name": "arbiterReward", "type": "uint256"},
        ],
        "name": "voidChallenge",
        "outputs": [],
        "type": "function",
    },
]


def _get_w3_and_contract():
    """Create web3 instance and contract object. Separated for mocking."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    abi = _load_escrow_abi()
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(ESCROW_CONTRACT_ADDRESS), abi=abi
    )
    return w3, contract


def _task_id_to_bytes32(task_id: str) -> bytes:
    """Convert task UUID string to bytes32 via keccak256."""
    return Web3.keccak(text=task_id)


def _send_tx(w3, contract_fn, description: str) -> str:
    """Build, sign, send a contract transaction. Returns tx hash hex."""
    account = w3.eth.account.from_key(PLATFORM_PRIVATE_KEY)
    tx = contract_fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 300_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    if receipt["status"] != 1:
        raise RuntimeError(f"{description} reverted (tx={tx_hash.hex()})")
    print(f"[escrow] {description} tx={tx_hash.hex()}", flush=True)
    return tx_hash.hex()


def check_usdc_balance(wallet_address: str) -> float:
    """Check USDC balance of a wallet. Returns amount in USDC (not wei)."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT), abi=ERC20_BALANCE_ABI
    )
    balance_wei = contract.functions.balanceOf(
        Web3.to_checksum_address(wallet_address)
    ).call()
    return balance_wei / 10**6


def create_challenge_onchain(
    task_id: str, winner_wallet: str, bounty: float, incentive: float
) -> str:
    """Call ChallengeEscrow.createChallenge(). Locks bounty (90%) into escrow.
    bounty = task.bounty * 0.95, incentive = 0.
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)
    bounty_wei = int(bounty * 10**6)
    incentive_wei = int(incentive * 10**6)

    fn = contract.functions.createChallenge(
        task_bytes,
        Web3.to_checksum_address(winner_wallet),
        bounty_wei,
        incentive_wei,
    )
    return _send_tx(w3, fn, f"createChallenge({task_id})")


def join_challenge_onchain(
    task_id: str,
    challenger_wallet: str,
    deposit_amount: float,
    deadline: int,
    v: int,
    r: str,
    s: str,
) -> str:
    """Call ChallengeEscrow.joinChallenge() with per-challenger deposit and EIP-2612 permit params.
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)
    deposit_wei = int(deposit_amount * 10**6)

    fn = contract.functions.joinChallenge(
        task_bytes,
        Web3.to_checksum_address(challenger_wallet),
        deposit_wei,
        deadline,
        v,
        bytes.fromhex(r[2:]) if r.startswith("0x") else bytes.fromhex(r),
        bytes.fromhex(s[2:]) if s.startswith("0x") else bytes.fromhex(s),
    )
    return _send_tx(w3, fn, f"joinChallenge({task_id}, {challenger_wallet})")


def void_challenge_onchain(
    task_id: str,
    publisher_wallet: str,
    publisher_refund: float,
    refunds: list[dict],
    arbiter_wallets: list[str],
    arbiter_reward: float,
) -> str:
    """Call ChallengeEscrow.voidChallenge() for voided tasks.
    refunds: [{"challenger": "0x...", "refund": True/False}, ...]
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)
    publisher_refund_wei = int(publisher_refund * 10**6)
    arbiter_reward_wei = int(arbiter_reward * 10**6)

    refund_tuples = [
        (
            Web3.to_checksum_address(r["challenger"]),
            r["refund"],
        )
        for r in refunds
    ]
    arbiter_addrs = [Web3.to_checksum_address(a) for a in arbiter_wallets]

    fn = contract.functions.voidChallenge(
        task_bytes,
        Web3.to_checksum_address(publisher_wallet),
        publisher_refund_wei,
        refund_tuples,
        arbiter_addrs,
        arbiter_reward_wei,
    )
    return _send_tx(w3, fn, f"voidChallenge({task_id})")


def resolve_challenge_onchain(
    task_id: str,
    final_winner_wallet: str,
    winner_payout: float,
    verdicts: list[dict],
) -> str:
    """Call ChallengeEscrow.resolveChallenge() V2 with per-challenge arbiter lists.
    verdicts: [{"challenger": "0x...", "result": 0|1|2, "arbiters": ["0x...", ...]}, ...]
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)
    winner_payout_wei = int(winner_payout * 10**6)

    verdict_tuples = [
        (
            Web3.to_checksum_address(v["challenger"]),
            v["result"],
            [Web3.to_checksum_address(a) for a in v.get("arbiters", [])],
        )
        for v in verdicts
    ]

    fn = contract.functions.resolveChallenge(
        task_bytes,
        Web3.to_checksum_address(final_winner_wallet),
        winner_payout_wei,
        verdict_tuples,
    )
    return _send_tx(w3, fn, f"resolveChallenge({task_id})")
