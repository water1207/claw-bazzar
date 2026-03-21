# Solana Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all Base EVM blockchain infrastructure (x402 payment, ChallengeEscrow, StakingVault, payout) with Solana Devnet equivalents.

**Architecture:** Bottom-up migration — backend services first (dependency swap, service rewrites), then Anchor programs (Rust), then frontend (TypeScript), finally tests and cleanup. Each task produces an independently committable change.

**Tech Stack:** Python `solana-py`/`solders` (backend), Anchor/Rust (on-chain programs), `@solana/web3.js`/`@solana/spl-token`/`@coral-xyz/anchor` (frontend), Solana Devnet, Circle Devnet USDC (`4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`)

**Spec:** `docs/superpowers/specs/2026-03-21-solana-migration-design.md`

---

## File Structure

### Backend (Python)

| File | Responsibility | Action |
|------|---------------|--------|
| `pyproject.toml` | Python deps | Modify: `web3` → `solana`+`solders`+`spl`, remove `fastapi-x402` |
| `app/services/x402.py` | x402 payment verification | Rewrite: Solana network/token params |
| `app/services/payout.py` | USDC payout to winners | Rewrite: SPL Token transfer via solana-py |
| `app/services/escrow.py` | ChallengeEscrow contract calls | Rewrite: Anchor instruction construction via solana-py |
| `app/services/staking.py` | StakingVault contract calls | Rewrite: Anchor instruction construction via solana-py |
| `app/services/solana_utils.py` | Shared Solana helpers | Create: client, keypair loading, ATA utils, discriminator builder |
| `app/schemas.py` | Pydantic request/response | Modify: remove Permit fields, add `signed_transaction`, fix wallet validation |
| `app/routers/challenges.py` | Challenge API | Modify: Permit flow → signed_transaction |
| `app/routers/users.py` | User registration | Modify: wallet dedup remove `.lower()` |
| `app/routers/trust.py` | Staking API | Modify: add staking endpoints using new `signed_transaction` schema |
| `app/routers/tasks.py` | Task creation API | Modify: verify env var refs, no EVM-specific code |
| `app/scheduler.py` | Background jobs | Modify: verify import paths after service rewrites |
| `.env.example` | Environment template | Create/Modify: document all Solana env vars |

### Anchor Programs (Rust)

| File | Responsibility | Action |
|------|---------------|--------|
| `Anchor.toml` | Anchor project config | Create |
| `programs/challenge-escrow/src/lib.rs` | Escrow program | Create |
| `programs/staking-vault/src/lib.rs` | Staking program | Create |
| `tests/anchor/challenge-escrow.ts` | Anchor integration tests | Create |
| `tests/anchor/staking-vault.ts` | Anchor integration tests | Create |

### Frontend (TypeScript)

| File | Responsibility | Action |
|------|---------------|--------|
| `frontend/package.json` | JS deps | Modify: remove `viem`, add Solana pkgs |
| `frontend/lib/x402.ts` | x402 payment signing | Rewrite: Solana transaction signing |
| `frontend/lib/sign-challenge.ts` | Challenge deposit signing | Create (replaces `permit.ts`) |
| `frontend/lib/sign-stake.ts` | Staking signing | Create |
| `frontend/lib/utils.ts` | Balance query | Modify: Solana RPC |
| `frontend/lib/dev-wallets.ts` | Dev wallet config | Rewrite: Solana Keypair format |
| `frontend/lib/idl/` | Anchor IDL files | Create (copied from Anchor build output) |
| `frontend/lib/permit.ts` | EIP-2612 Permit | Delete |
| `frontend/lib/permit.test.ts` | Permit tests | Delete |
| `frontend/components/DevPanel.tsx` | Dev testing UI | Modify: Solana signing flow |
| `frontend/components/SettlementPanel.tsx` | Settlement display | Modify: explorer link |
| `frontend/components/TaskDetail.tsx` | Task detail view | Modify: explorer link |
| `frontend/components/BalanceTrustHistoryPanel.tsx` | Balance history | Modify: explorer link |
| `frontend/components/ChallengePanel.tsx` | Challenge UI | Modify: address format |
| `frontend/components/LeaderboardTable.tsx` | Leaderboard | Modify: address truncation |
| `frontend/components/ProfileView.tsx` | User profile | Modify: address truncation |

### Cleanup

| File | Action |
|------|--------|
| `contracts/` | Delete entire directory |
| `CLAUDE.md` | Update: commands, env vars, architecture |

---

## Task 1: Python 依赖替换

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml dependencies**

Replace `web3` and `fastapi-x402` with Solana packages:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "apscheduler>=3.10.0",
    "solana>=0.35.0",
    "solders>=0.25.0",
    "spl>=0.1.0",
    "python-dotenv>=1.0.0",
    "psycopg2-binary>=2.9.0",
]
```

- [ ] **Step 2: Install new dependencies**

Run: `pip install -e ".[dev]"`
Expected: Successful installation, no errors

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: replace web3 with solana-py/solders dependencies"
```

---

## Task 2: 共享 Solana 工具模块

**Files:**
- Create: `app/services/solana_utils.py`
- Test: `tests/test_solana_utils.py`

- [ ] **Step 1: Write tests for Solana utility functions**

```python
# tests/test_solana_utils.py
import hashlib
from app.services.solana_utils import (
    task_id_to_seed,
    build_anchor_discriminator,
    usdc_to_lamports,
    lamports_to_usdc,
)


def test_task_id_to_seed():
    seed = task_id_to_seed("test-uuid-123")
    assert len(seed) == 32
    assert seed == hashlib.sha256(b"test-uuid-123").digest()


def test_build_anchor_discriminator():
    disc = build_anchor_discriminator("create_challenge")
    assert len(disc) == 8
    expected = hashlib.sha256(b"global:create_challenge").digest()[:8]
    assert disc == expected


def test_usdc_to_lamports():
    assert usdc_to_lamports(1.0) == 1_000_000
    assert usdc_to_lamports(0.01) == 10_000
    assert usdc_to_lamports(100.5) == 100_500_000


def test_lamports_to_usdc():
    assert lamports_to_usdc(1_000_000) == 1.0
    assert lamports_to_usdc(10_000) == 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_solana_utils.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement solana_utils.py**

```python
# app/services/solana_utils.py
"""Shared Solana utilities for backend services."""
import hashlib
import json
import os

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID

SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
USDC_MINT = Pubkey.from_string(
    os.environ.get("USDC_MINT", "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
)
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "")
ESCROW_PROGRAM_ID = os.environ.get("ESCROW_PROGRAM_ID", "")
STAKING_PROGRAM_ID = os.environ.get("STAKING_PROGRAM_ID", "")


def get_client() -> Client:
    return Client(SOLANA_RPC_URL)


def get_platform_keypair() -> Keypair:
    raw = os.environ.get("PLATFORM_PRIVATE_KEY", "[]")
    secret = bytes(json.loads(raw))
    return Keypair.from_bytes(secret)


def task_id_to_seed(task_id: str) -> bytes:
    """Convert task UUID to 32-byte seed via SHA-256."""
    return hashlib.sha256(task_id.encode()).digest()


def build_anchor_discriminator(method_name: str) -> bytes:
    """Compute Anchor 8-byte instruction discriminator."""
    return hashlib.sha256(f"global:{method_name}".encode()).digest()[:8]


def usdc_to_lamports(amount: float) -> int:
    """Convert USDC amount to smallest unit (6 decimals)."""
    return int(amount * 10**6)


def lamports_to_usdc(lamports: int) -> float:
    """Convert smallest unit back to USDC."""
    return lamports / 10**6


def find_pda(seeds: list[bytes], program_id: Pubkey) -> tuple[Pubkey, int]:
    """Find PDA for given seeds and program."""
    return Pubkey.find_program_address(seeds, program_id)


def get_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive Associated Token Account address."""
    ata, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return ata


def build_instruction(
    program_id: Pubkey,
    method_name: str,
    args_data: bytes,
    accounts: list[AccountMeta],
) -> Instruction:
    """Build an Anchor instruction with discriminator + serialized args."""
    discriminator = build_anchor_discriminator(method_name)
    data = discriminator + args_data
    return Instruction(program_id, data, accounts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_solana_utils.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/solana_utils.py tests/test_solana_utils.py
git commit -m "feat: add shared Solana utility module"
```

---

## Task 3: 后端 x402 服务迁移

**Files:**
- Rewrite: `app/services/x402.py`
- Modify: `tests/test_tasks.py` (mock pattern stays the same — `verify_payment` is mocked at router level)

- [ ] **Step 1: Rewrite x402.py with Solana parameters**

```python
# app/services/x402.py
import os
import json
import base64

import httpx

FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "")
X402_NETWORK = os.environ.get("X402_NETWORK", "solana-devnet")
USDC_MINT = os.environ.get("USDC_MINT", "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")


def build_payment_requirements(bounty: float) -> dict:
    """Build x402 payment requirements for a given bounty amount."""
    return {
        "scheme": "exact",
        "network": X402_NETWORK,
        "asset": USDC_MINT,
        "amount": str(int(bounty * 1e6)),
        "payTo": PLATFORM_WALLET,
        "maxTimeoutSeconds": 30,
    }


def _facilitator_verify(payment_header: str, requirements: dict) -> dict:
    """Call the x402 facilitator to verify then settle a payment. Separated for easy mocking."""
    try:
        decoded = json.loads(base64.b64decode(payment_header))
        payload = {"paymentPayload": decoded, "paymentRequirements": requirements}

        # Step 1: verify signature
        verify_resp = httpx.post(
            f"{FACILITATOR_URL}/verify",
            json=payload,
            timeout=30,
            follow_redirects=True,
            verify=False,
        )
        verify_data = verify_resp.json()
        print(f"[x402] verify status={verify_resp.status_code} body={verify_data}", flush=True)
        if not verify_data.get("isValid", False):
            reason = verify_data.get("invalidReason") or verify_data.get("error") or "signature verification failed"
            return {"valid": False, "tx_hash": None, "reason": f"verify: {reason}"}

        # Step 2: settle (executes the on-chain USDC transfer)
        settle_resp = httpx.post(
            f"{FACILITATOR_URL}/settle",
            json=payload,
            timeout=30,
            follow_redirects=True,
            verify=False,
        )
        settle_data = settle_resp.json()
        print(f"[x402] settle status={settle_resp.status_code} body={settle_data}", flush=True)
        if settle_resp.status_code != 200 or not settle_data.get("success", False):
            reason = settle_data.get("error") or f"settle failed (HTTP {settle_resp.status_code})"
            return {"valid": False, "tx_hash": None, "reason": f"settle: {reason}"}

        return {"valid": True, "tx_hash": settle_data.get("transaction")}
    except httpx.TimeoutException:
        print("[x402] facilitator timeout", flush=True)
        return {"valid": False, "tx_hash": None, "reason": "facilitator timeout"}
    except Exception as e:
        print(f"[x402] exception: {e}", flush=True)
        return {"valid": False, "tx_hash": None, "reason": str(e)}


def verify_payment(payment_header: str | None, bounty: float) -> dict:
    """Verify an x402 payment header for a given bounty amount."""
    if not payment_header:
        return {"valid": False, "tx_hash": None}
    requirements = build_payment_requirements(bounty)
    return _facilitator_verify(payment_header, requirements)
```

Key changes: removed `USDC_CONTRACT` → `USDC_MINT`, removed EIP-3009 `extra` block, changed default network to `solana-devnet`.

- [ ] **Step 2: Run existing backend tests**

Run: `pytest tests/test_tasks.py -v`
Expected: All pass (payment is mocked at router level via `verify_payment`, x402 internals don't affect tests)

- [ ] **Step 3: Commit**

```bash
git add app/services/x402.py
git commit -m "feat: migrate x402 service to Solana parameters"
```

---

## Task 4: 后端 Payout 服务迁移

**Files:**
- Rewrite: `app/services/payout.py`

- [ ] **Step 1: Rewrite payout.py with solana-py**

```python
# app/services/payout.py
import os
from sqlalchemy.orm import Session
from ..models import Task, Submission, User, PayoutStatus
from .solana_utils import (
    get_client, get_platform_keypair, get_associated_token_address,
    usdc_to_lamports, USDC_MINT,
)
from solders.pubkey import Pubkey
from solana.transaction import Transaction
from solana.rpc.types import TxOpts
from spl.token.instructions import transfer_checked, TransferCheckedParams
from spl.token.instructions import create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID

PLATFORM_FEE_RATE = float(os.environ.get("PLATFORM_FEE_RATE", "0.20"))


def _send_usdc_transfer(to_address: str, amount: float) -> str:
    """Send USDC (SPL Token) transfer on Solana. Returns tx signature."""
    client = get_client()
    payer = get_platform_keypair()
    to_pubkey = Pubkey.from_string(to_address)

    payer_ata = get_associated_token_address(payer.pubkey(), USDC_MINT)
    to_ata = get_associated_token_address(to_pubkey, USDC_MINT)
    amount_lamports = usdc_to_lamports(amount)

    tx = Transaction()

    # Create recipient ATA if it doesn't exist
    try:
        acct_info = client.get_account_info(to_ata)
        if acct_info.value is None:
            tx.add(
                create_associated_token_account(payer.pubkey(), to_pubkey, USDC_MINT)
            )
    except Exception:
        tx.add(
            create_associated_token_account(
                CreateAssociatedTokenAccountParams(
                    payer=payer.pubkey(),
                    owner=to_pubkey,
                    mint=USDC_MINT,
                )
            )
        )

    tx.add(
        transfer_checked(
            TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=payer_ata,
                mint=USDC_MINT,
                dest=to_ata,
                owner=payer.pubkey(),
                amount=amount_lamports,
                decimals=6,
            )
        )
    )

    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
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

    submission = db.query(Submission).filter(
        Submission.id == task.winner_submission_id
    ).first()
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
```

- [ ] **Step 2: Update payout mock targets in tests**

Any test file that mocks `app.services.payout._send_usdc_transfer` should still work (function name unchanged). But if any test mocks web3 internals like `Web3.HTTPProvider`, update those mock paths. Search for `web3` references in test files and replace mock targets:
```python
# Mock target stays the same (function name unchanged):
patch("app.services.payout._send_usdc_transfer", return_value="5VERv8NMvzbJMEkV8xnrLkEaWRtSz9...")
```

- [ ] **Step 3: Run backend tests**

Run: `pytest tests/test_tasks.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add app/services/payout.py tests/
git commit -m "feat: migrate payout service to Solana SPL Token transfer"
```

---

## Task 5: API Schema 适配

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/routers/users.py`

- [ ] **Step 1: Update UserCreate wallet validator — remove `.lower()`**

In `app/schemas.py`, change `normalize_wallet`:

```python
class UserCreate(BaseModel):
    nickname: str
    wallet: str
    role: UserRole

    @field_validator("wallet")
    @classmethod
    def validate_wallet(cls, v: str) -> str:
        # Solana Base58 addresses are case-sensitive, no lowering
        if not v or len(v) < 32 or len(v) > 44:
            raise ValueError("Invalid Solana wallet address")
        return v
```

- [ ] **Step 2: Update ChallengeCreate — remove Permit fields, add signed_transaction**

```python
class ChallengeCreate(BaseModel):
    challenger_submission_id: str
    reason: str
    challenger_wallet: str
    signed_transaction: str  # base64-encoded signed Solana transaction
```

- [ ] **Step 3: Update StakeRequest — remove Permit fields, add signed_transaction**

```python
class StakeRequest(BaseModel):
    amount: float
    purpose: StakePurpose
    signed_transaction: str  # base64-encoded signed Solana transaction
```

- [ ] **Step 4: Update users.py — remove `.lower()` from wallet dedup**

In `app/routers/users.py`, change the wallet lookup:

```python
# Before:
existing_wallet = db.query(User).filter(
    func.lower(User.wallet) == data.wallet.lower()
).first()

# After:
existing_wallet = db.query(User).filter(
    User.wallet == data.wallet
).first()
```

Also remove `from sqlalchemy import func` if no longer used.

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v -k "test_create_user or test_register"`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/schemas.py app/routers/users.py
git commit -m "feat: adapt schemas for Solana (remove Permit, fix wallet validation)"
```

---

## Task 6: 后端 Escrow 服务迁移

**Files:**
- Rewrite: `app/services/escrow.py`

- [ ] **Step 1: Rewrite escrow.py with Solana instructions**

```python
# app/services/escrow.py
"""ChallengeEscrow Anchor program interaction layer."""
import struct
from .solana_utils import (
    get_client, get_platform_keypair, get_associated_token_address,
    task_id_to_seed, usdc_to_lamports, lamports_to_usdc,
    build_instruction, find_pda, USDC_MINT,
)
from solders.pubkey import Pubkey
from solana.transaction import Transaction
from solana.rpc.types import TxOpts
from solders.instruction import AccountMeta
from spl.token.constants import TOKEN_PROGRAM_ID
import os

ESCROW_PROGRAM_ID = Pubkey.from_string(
    os.environ.get("ESCROW_PROGRAM_ID", "11111111111111111111111111111111")
)


def _get_escrow_pdas(task_id: str):
    """Derive all PDAs needed for escrow instructions."""
    task_seed = task_id_to_seed(task_id)
    challenge_pda, challenge_bump = find_pda([b"challenge", task_seed], ESCROW_PROGRAM_ID)
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

    # Borsh serialize: task_id_hash(32) + bounty(u64) + incentive(u64)
    args = task_seed + struct.pack("<QQ", bounty_lamports, incentive_lamports)

    payer_ata = get_associated_token_address(payer.pubkey(), USDC_MINT)

    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),     # authority
        AccountMeta(config_pda, is_signer=False, is_writable=False),       # config
        AccountMeta(challenge_pda, is_signer=False, is_writable=True),     # challenge_info
        AccountMeta(vault_pda, is_signer=False, is_writable=True),         # escrow_vault
        AccountMeta(payer_ata, is_signer=False, is_writable=True),         # authority_ata
        AccountMeta(winner_pubkey, is_signer=False, is_writable=False),    # winner
        AccountMeta(USDC_MINT, is_signer=False, is_writable=False),        # mint
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False), # token_program
        AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), is_signer=False, is_writable=False),  # system_program
    ]

    ix = build_instruction(ESCROW_PROGRAM_ID, "create_challenge", args, accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    sig = str(resp.value)
    print(f"[escrow] createChallenge({task_id}) tx={sig}", flush=True)
    return sig


def join_challenge_onchain(task_id: str, signed_transaction: str) -> str:
    """Submit a pre-signed join_challenge transaction to the network."""
    import base64
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
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(config_pda, is_signer=False, is_writable=False),
        AccountMeta(challenge_pda, is_signer=False, is_writable=True),
        AccountMeta(vault_pda, is_signer=False, is_writable=True),
        AccountMeta(vault_authority_pda, is_signer=False, is_writable=False),
        AccountMeta(USDC_MINT, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    # Remaining accounts: winner ATA, then refund ATAs, then arbiter ATAs
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
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(config_pda, is_signer=False, is_writable=False),
        AccountMeta(challenge_pda, is_signer=False, is_writable=True),
        AccountMeta(vault_pda, is_signer=False, is_writable=True),
        AccountMeta(vault_authority_pda, is_signer=False, is_writable=False),
        AccountMeta(USDC_MINT, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    # Remaining accounts: publisher ATA, refund ATAs, arbiter ATAs
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

    ix = build_instruction(ESCROW_PROGRAM_ID, "void_challenge", args, accounts)
    tx = Transaction().add(ix)
    resp = client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
    sig = str(resp.value)
    print(f"[escrow] voidChallenge({task_id}) tx={sig}", flush=True)
    return sig
```

- [ ] **Step 2: Update escrow mock targets in tests**

Replace any test mocks targeting web3 escrow internals:
```python
# Before:
patch("app.services.escrow._get_w3_and_contract", ...)
patch("app.services.escrow._send_tx", return_value="0xtest")

# After:
patch("app.services.escrow.get_client", ...)
patch("app.services.escrow.create_challenge_onchain", return_value="5VERv...")
patch("app.services.escrow.join_challenge_onchain", return_value="5VERv...")
patch("app.services.escrow.resolve_challenge_onchain", return_value="5VERv...")
patch("app.services.escrow.void_challenge_onchain", return_value="5VERv...")
```

Note: `join_challenge_onchain` now takes `(task_id, signed_transaction)` instead of 7 permit args.

- [ ] **Step 3: Run challenge tests**

Run: `pytest tests/test_challenge_api.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add app/services/escrow.py tests/
git commit -m "feat: migrate escrow service to Solana Anchor instructions"
```

---

## Task 7: 后端 Staking 服务迁移

**Files:**
- Rewrite: `app/services/staking.py`

- [ ] **Step 1: Rewrite staking.py with Solana instructions**

Replace all `from web3 import Web3` blocks with Solana equivalents. Key changes:

- `stake_onchain()`: accept `signed_transaction: str` instead of permit params; submit pre-signed tx
- `slash_onchain()`: build Anchor `slash` instruction with authority signing
- `unstake()`: build Anchor `unstake` instruction with authority signing
- Remove all `Web3`, `HTTPProvider`, `build_transaction`, `sign_transaction` calls

```python
# app/services/staking.py
import os
import struct
import base64
import logging
from sqlalchemy.orm import Session
from app.models import User, StakeRecord, StakePurpose, TrustTier
from app.services.trust import apply_event, TrustEventType
from app.services.solana_utils import (
    get_client, get_platform_keypair, get_associated_token_address,
    find_pda, build_instruction, usdc_to_lamports, USDC_MINT,
)
from solders.pubkey import Pubkey
from solders.instruction import AccountMeta
from solana.transaction import Transaction
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
    db: Session, user_id: str, signed_transaction: str,
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
    db: Session, user_id: str, amount: float, signed_transaction: str,
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
```

- [ ] **Step 2: Update staking mock targets in tests**

Replace any test mocks targeting web3 staking internals:
```python
# Before:
patch("app.services.staking.stake_onchain", return_value="0xtest")
# After (new signature: signed_transaction instead of permit params):
patch("app.services.staking.stake_onchain", return_value="5VERv...")
patch("app.services.staking.slash_onchain", return_value="5VERv...")
```

Also update callers of `stake_for_arbiter`/`stake_for_credit` — they now take `signed_transaction: str` instead of `deadline, v, r, s`.

- [ ] **Step 3: Run backend tests**

Run: `pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add app/services/staking.py tests/
git commit -m "feat: migrate staking service to Solana Anchor instructions"
```

---

## Task 8: 后端 Router 更新

**Files:**
- Modify: `app/routers/challenges.py`

- [ ] **Step 1: Update challenge join endpoint**

In `app/routers/challenges.py`, replace the Permit-based `join_challenge_onchain()` call:

```python
# Before (around lines 93-104):
deposit_tx_hash = join_challenge_onchain(
    task_id, data.challenger_wallet, deposit_amount,
    data.permit_deadline, data.permit_v, data.permit_r, data.permit_s
)

# After:
deposit_tx_hash = join_challenge_onchain(
    task_id, data.signed_transaction
)
```

Also remove the `if data.permit_v is not None:` guard — the new `signed_transaction` field is required in the schema.

- [ ] **Step 2: Run challenge tests**

Run: `pytest tests/test_challenge_api.py -v`
Expected: May need mock updates — update test mocks for new `join_challenge_onchain` signature

- [ ] **Step 3: Update test mocks if needed**

In test files that mock `join_challenge_onchain`, update the mock to match the new 2-arg signature `(task_id, signed_transaction)` instead of the old 7-arg signature.

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add app/routers/challenges.py tests/
git commit -m "feat: update challenge router for Solana signed_transaction flow"
```

---

## Task 8b: Staking Router + Scheduler/Tasks 检查

**Files:**
- Modify: `app/routers/trust.py`
- Modify: `app/routers/tasks.py`
- Modify: `app/scheduler.py`
- Create: `.env.example`

- [ ] **Step 1: Add staking API endpoints to trust.py**

Add `POST /users/{user_id}/stake` endpoint that accepts `StakeRequest` with `signed_transaction`, calls `stake_for_arbiter()` or `stake_for_credit()` from the rewritten staking service.

- [ ] **Step 2: Verify tasks.py has no EVM-specific code**

Check `app/routers/tasks.py` for any direct references to `web3`, `USDC_CONTRACT`, `0x` addresses, etc. The x402 payment flow is already mocked via `verify_payment()` which was updated in Task 3. Fix any remaining EVM references.

- [ ] **Step 3: Verify scheduler.py import paths**

Check `app/scheduler.py` calls to `create_challenge_onchain`, `resolve_challenge_onchain`, `void_challenge_onchain` — verify the import paths and function signatures still match after Task 6 rewrites. The function names are unchanged but `join_challenge_onchain` now takes `(task_id, signed_transaction)` instead of 7 args.

- [ ] **Step 4: Create .env.example with Solana vars**

```env
# Solana
SOLANA_RPC_URL=https://api.devnet.solana.com
USDC_MINT=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
PLATFORM_WALLET=<Base58 pubkey>
PLATFORM_PRIVATE_KEY=<JSON byte array, 64 bytes, e.g. [1,2,3,...]>

# Programs
ESCROW_PROGRAM_ID=<program pubkey after anchor deploy>
STAKING_PROGRAM_ID=<program pubkey after anchor deploy>

# x402
FACILITATOR_URL=https://x402.org/facilitator
X402_NETWORK=solana-devnet

# Frontend (in frontend/.env.local)
# NEXT_PUBLIC_ESCROW_PROGRAM_ID=<same as ESCROW_PROGRAM_ID>
# NEXT_PUBLIC_STAKING_PROGRAM_ID=<same as STAKING_PROGRAM_ID>
# NEXT_PUBLIC_PLATFORM_WALLET=<same as PLATFORM_WALLET>
# NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY=<base64 encoded 64-byte keypair>
```

- [ ] **Step 5: Run all backend tests**

Run: `pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/routers/trust.py app/routers/tasks.py app/scheduler.py .env.example
git commit -m "feat: add staking routes, verify scheduler/tasks, add .env.example"
```

---

## Task 9: Anchor ChallengeEscrow 程序

**Files:**
- Create: `Anchor.toml`
- Create: `programs/challenge-escrow/Cargo.toml`
- Create: `programs/challenge-escrow/src/lib.rs`

- [ ] **Step 1: Initialize Anchor project structure**

Run: `anchor init claw-bazzar-programs --no-git` (or manually create files)

Create `Anchor.toml`:

```toml
[toolchain]

[features]
seeds = false
skip-lint = false

[programs.devnet]
challenge_escrow = "PLACEHOLDER_PROGRAM_ID"
staking_vault = "PLACEHOLDER_PROGRAM_ID"

[registry]
url = "https://api.apr.dev"

[provider]
cluster = "devnet"
wallet = "~/.config/solana/id.json"

[scripts]
test = "npx ts-mocha -p ./tsconfig.json -t 1000000 tests/anchor/**/*.ts"
```

- [ ] **Step 2: Write ChallengeEscrow program**

Create `programs/challenge-escrow/src/lib.rs` with:
- `initialize` instruction (sets authority + USDC mint in Config PDA)
- `create_challenge` instruction (locks bounty + incentive from authority ATA → vault)
- `join_challenge` instruction (transfers deposit + service fee from challenger ATA → vault)
- `resolve_challenge` instruction (distributes from vault → winner/refunds/arbiters/platform via remaining accounts)
- `void_challenge` instruction (refunds publisher, distributes deposits)
- `emergency_withdraw` instruction (30-day timeout)

Account structs: `Config`, `ChallengeInfo`, `ChallengerRecord`
Events: `ChallengeCreated`, `ChallengerJoined`, `ChallengeResolved`

This is a significant Rust file (~500 lines). Implement the full Anchor program per the spec (Section 3). Reference the existing Solidity contract logic in `contracts/src/ChallengeEscrow.sol` for business rules.

- [ ] **Step 3: Build the program**

Run: `anchor build`
Expected: Successful compilation, IDL generated at `target/idl/challenge_escrow.json`

- [ ] **Step 4: Copy IDL to frontend**

```bash
mkdir -p frontend/lib/idl
cp target/idl/challenge_escrow.json frontend/lib/idl/
```

- [ ] **Step 5: Commit**

```bash
git add Anchor.toml programs/challenge-escrow/ frontend/lib/idl/challenge_escrow.json
git commit -m "feat: add ChallengeEscrow Anchor program"
```

---

## Task 10: Anchor StakingVault 程序

**Files:**
- Create: `programs/staking-vault/Cargo.toml`
- Create: `programs/staking-vault/src/lib.rs`

- [ ] **Step 1: Write StakingVault program**

Create `programs/staking-vault/src/lib.rs` with:
- `initialize` instruction (sets authority, USDC mint, creates vault token account)
- `stake` instruction (user signs, transfers from user ATA → vault)
- `unstake` instruction (authority signs, transfers from vault → user ATA)
- `slash` instruction (authority signs, transfers from vault → platform ATA)
- `emergency_withdraw` instruction (authority signs, 30-day check)

Account structs: `Config`, `StakeRecord`

Reference existing Solidity contract `contracts/src/StakingVault.sol`.

- [ ] **Step 2: Build**

Run: `anchor build`
Expected: Both programs compile

- [ ] **Step 3: Copy IDL**

```bash
cp target/idl/staking_vault.json frontend/lib/idl/
```

- [ ] **Step 4: Commit**

```bash
git add programs/staking-vault/ frontend/lib/idl/staking_vault.json
git commit -m "feat: add StakingVault Anchor program"
```

---

## Task 11: Anchor 程序测试

**Files:**
- Create: `tests/anchor/challenge-escrow.ts`
- Create: `tests/anchor/staking-vault.ts`

- [ ] **Step 1: Write ChallengeEscrow integration tests**

Test coverage:
- Initialize program with authority
- Create challenge (locks bounty + incentive)
- Join challenge (challenger deposits)
- Resolve challenge (distributes to winner, refunds, arbiters)
- Void challenge (refunds publisher)
- Emergency withdraw (after 30 days)

Uses `solana-test-validator` with a mock USDC mint created via `createMint()`.

- [ ] **Step 2: Write StakingVault integration tests**

Test coverage:
- Initialize + create vault
- Stake (user deposits 100 USDC)
- Slash (authority confiscates)
- Unstake (authority returns)

- [ ] **Step 3: Run tests**

Run: `anchor test`
Expected: All tests pass on local validator

- [ ] **Step 4: Commit**

```bash
git add tests/anchor/
git commit -m "test: add Anchor program integration tests"
```

---

## Task 12: 前端依赖替换

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Update frontend dependencies**

```bash
cd frontend
npm uninstall viem
npm install @solana/web3.js @solana/spl-token @coral-xyz/anchor
```

- [ ] **Step 2: Verify build still works (will have TS errors — expected)**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: Errors about missing viem imports (this is expected, will fix in next tasks)

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: replace viem with Solana packages in frontend"
```

---

## Task 13: 前端 x402 支付签名

**Files:**
- Rewrite: `frontend/lib/x402.ts`
- Rewrite: `frontend/lib/x402.test.ts`

- [ ] **Step 1: Rewrite x402.test.ts**

```typescript
// frontend/lib/x402.test.ts
import { describe, it, expect } from 'vitest'
import { signX402Payment, getDevWalletAddress } from './x402'

// Generate a valid test keypair at import time
import { Keypair } from '@solana/web3.js'
const TEST_KEYPAIR = Keypair.generate()
const TEST_SECRET_BASE64 = Buffer.from(TEST_KEYPAIR.secretKey).toString('base64')

describe('x402 Solana', () => {
  it('getDevWalletAddress returns Base58 pubkey', () => {
    const address = getDevWalletAddress(TEST_SECRET_BASE64)
    expect(address).toBeTruthy()
    expect(address.length).toBeGreaterThanOrEqual(32)
    expect(address.length).toBeLessThanOrEqual(44)
  })

  it('signX402Payment returns base64 payload', async () => {
    const result = await signX402Payment({
      secretKey: TEST_SECRET_BASE64,
      payTo: getDevWalletAddress(TEST_SECRET_BASE64),
      amount: 1.0,
    })
    expect(typeof result).toBe('string')
    // Should be valid base64
    const decoded = JSON.parse(atob(result))
    expect(decoded.x402Version).toBe(2)
    expect(decoded.accepted.network).toBe('solana-devnet')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest lib/x402.test.ts`
Expected: FAIL

- [ ] **Step 3: Rewrite x402.ts**

```typescript
// frontend/lib/x402.ts
import { Keypair, Connection, Transaction, PublicKey } from '@solana/web3.js'
import { createTransferCheckedInstruction, getAssociatedTokenAddress } from '@solana/spl-token'
import bs58 from 'bs58'

const USDC_MINT = new PublicKey('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU')
const SOLANA_RPC = 'https://api.devnet.solana.com'
const X402_VERSION = 2

export function getDevWalletAddress(secretKeyBase64: string): string {
  const secret = Buffer.from(secretKeyBase64, 'base64')
  const keypair = Keypair.fromSecretKey(secret)
  return keypair.publicKey.toBase58()
}

export async function signX402Payment(params: {
  secretKey: string  // base64 encoded 64-byte secret key
  payTo: string      // Solana pubkey (Base58)
  amount: number     // USDC amount
}): Promise<string> {
  const { secretKey, payTo, amount } = params
  const keypair = Keypair.fromSecretKey(Buffer.from(secretKey, 'base64'))
  const connection = new Connection(SOLANA_RPC)
  const amountLamports = Math.round(amount * 1e6)

  const fromAta = await getAssociatedTokenAddress(USDC_MINT, keypair.publicKey)
  const toAta = await getAssociatedTokenAddress(USDC_MINT, new PublicKey(payTo))

  const tx = new Transaction().add(
    createTransferCheckedInstruction(
      fromAta, USDC_MINT, toAta,
      keypair.publicKey, amountLamports, 6,
    )
  )

  const { blockhash } = await connection.getLatestBlockhash()
  tx.recentBlockhash = blockhash
  tx.feePayer = keypair.publicKey
  tx.sign(keypair)

  const serialized = tx.serialize()
  const amountStr = amountLamports.toString()

  const paymentPayload = {
    x402Version: X402_VERSION,
    resource: {
      url: 'task-creation',
      description: 'Task creation payment',
      mimeType: 'application/json',
    },
    accepted: {
      scheme: 'exact',
      network: 'solana-devnet',
      asset: USDC_MINT.toBase58(),
      amount: amountStr,
      payTo,
      maxTimeoutSeconds: 30,
    },
    payload: {
      transaction: Buffer.from(serialized).toString('base64'),
    },
  }

  return btoa(JSON.stringify(paymentPayload))
}
```

- [ ] **Step 4: Run test**

Run: `cd frontend && npx vitest lib/x402.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/x402.ts frontend/lib/x402.test.ts
git commit -m "feat: rewrite x402 payment signing for Solana"
```

---

## Task 14: 前端 Challenge/Staking 签名

**Files:**
- Delete: `frontend/lib/permit.ts`
- Delete: `frontend/lib/permit.test.ts`
- Create: `frontend/lib/sign-challenge.ts`
- Create: `frontend/lib/sign-stake.ts`

- [ ] **Step 1: Delete permit files**

```bash
rm frontend/lib/permit.ts frontend/lib/permit.test.ts
```

- [ ] **Step 2: Create sign-challenge.ts**

Build `join_challenge` Anchor instruction, sign with user Keypair, return base64 serialized transaction for backend submission.

Uses IDL from `frontend/lib/idl/challenge_escrow.json`, derives PDAs, computes user ATA.

- [ ] **Step 3: Create sign-stake.ts**

Same pattern for staking `stake` instruction.

- [ ] **Step 4: Write tests for sign-challenge and sign-stake**

Create `frontend/lib/sign-challenge.test.ts`:
- Test that `signJoinChallenge()` returns a valid base64 string
- Test PDA derivation produces expected seed format
- Mock `@solana/web3.js` Connection to avoid real RPC calls

Create `frontend/lib/sign-stake.test.ts`:
- Test that `signStake()` returns a valid base64 string

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest lib/sign-challenge.test.ts lib/sign-stake.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A frontend/lib/permit.ts frontend/lib/permit.test.ts
git add frontend/lib/sign-challenge.ts frontend/lib/sign-challenge.test.ts
git add frontend/lib/sign-stake.ts frontend/lib/sign-stake.test.ts
git commit -m "feat: replace EIP-2612 Permit with Solana transaction signing"
```

---

## Task 15: 前端 Utils + Dev Wallets

**Files:**
- Modify: `frontend/lib/utils.ts`
- Rewrite: `frontend/lib/dev-wallets.ts`

- [ ] **Step 1: Update fetchUsdcBalance in utils.ts**

Replace the EVM `eth_call` with Solana RPC:

```typescript
const SOLANA_RPC = 'https://api.devnet.solana.com'
const USDC_MINT = '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU'

export async function fetchUsdcBalance(address: string): Promise<string> {
  const { PublicKey } = await import('@solana/web3.js')
  const { getAssociatedTokenAddress } = await import('@solana/spl-token')

  const owner = new PublicKey(address)
  const mint = new PublicKey(USDC_MINT)
  const ata = await getAssociatedTokenAddress(mint, owner)

  const resp = await fetch(SOLANA_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      method: 'getTokenAccountBalance',
      params: [ata.toBase58()],
      id: 1,
    }),
  })
  const json = await resp.json()
  if (json.error) return '0.00'
  return (json.result?.value?.uiAmountString ?? '0.00')
}
```

Remove `BASE_SEPOLIA_RPC` and `USDC_CONTRACT` constants.

- [ ] **Step 2: Rewrite dev-wallets.ts**

```typescript
// frontend/lib/dev-wallets.ts
export interface DevUser {
  key: string  // base64-encoded 64-byte Solana secret key
  nickname: string
  storageKey: string
  role: 'publisher' | 'worker' | 'arbiter'
  trustScore?: number
  label?: string
}

export const DEV_PUBLISHER: DevUser | null = process.env.NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY
  ? { key: process.env.NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY, nickname: 'dev-publisher', storageKey: 'devPublisherId', role: 'publisher', trustScore: 850, label: 'Publisher' }
  : null

export const DEV_WORKERS: DevUser[] = [
  { key: process.env.NEXT_PUBLIC_DEV_WORKER_WALLET_KEY!,  nickname: 'Alice',   storageKey: 'devWorkerId',   role: 'worker', trustScore: 850 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER2_WALLET_KEY!, nickname: 'Bob',     storageKey: 'devWorker2Id',  role: 'worker', trustScore: 550 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER3_WALLET_KEY!, nickname: 'Charlie', storageKey: 'devWorker3Id',  role: 'worker', trustScore: 350 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER4_WALLET_KEY!, nickname: 'Diana',   storageKey: 'devWorker4Id',  role: 'worker', trustScore: 400 },
  { key: process.env.NEXT_PUBLIC_DEV_WORKER5_WALLET_KEY!, nickname: 'Ethan',   storageKey: 'devWorker5Id',  role: 'worker', trustScore: 200 },
].filter((w) => w.key)

export const DEV_ARBITERS: DevUser[] = [
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER1_WALLET_KEY!, nickname: 'arbiter-alpha', storageKey: 'devArbiter1Id', role: 'arbiter', label: 'Arbiter α' },
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER2_WALLET_KEY!, nickname: 'arbiter-beta',  storageKey: 'devArbiter2Id', role: 'arbiter', label: 'Arbiter β' },
  { key: process.env.NEXT_PUBLIC_DEV_ARBITER3_WALLET_KEY!, nickname: 'arbiter-gamma', storageKey: 'devArbiter3Id', role: 'arbiter', label: 'Arbiter γ' },
].filter((a) => a.key)

export const ALL_DEV_USERS: { label: string; key: string; nickname: string }[] = [
  ...(DEV_PUBLISHER ? [{ label: DEV_PUBLISHER.label ?? DEV_PUBLISHER.nickname, key: DEV_PUBLISHER.storageKey, nickname: DEV_PUBLISHER.nickname }] : []),
  ...DEV_WORKERS.map((w) => ({ label: w.label ?? w.nickname, key: w.storageKey, nickname: w.nickname })),
  ...DEV_ARBITERS.map((a) => ({ label: a.label ?? a.nickname, key: a.storageKey, nickname: a.nickname })),
]
```

Key change: `type { Hex }` removed, `key` is now `string` (base64) instead of `Hex`.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/utils.ts frontend/lib/dev-wallets.ts
git commit -m "feat: migrate utils and dev-wallets to Solana"
```

---

## Task 16: 前端组件更新

**Files:**
- Modify: `frontend/components/SettlementPanel.tsx`
- Modify: `frontend/components/TaskDetail.tsx`
- Modify: `frontend/components/BalanceTrustHistoryPanel.tsx`
- Modify: `frontend/components/DevPanel.tsx`
- Modify: `frontend/components/ChallengePanel.tsx`
- Modify: `frontend/components/LeaderboardTable.tsx`
- Modify: `frontend/components/ProfileView.tsx`

- [ ] **Step 1: Replace explorer links**

In `SettlementPanel.tsx` and `TaskDetail.tsx`, replace:
```typescript
// Before:
const BASE_SEPOLIA_EXPLORER = 'https://sepolia.basescan.org/tx'
// After:
const SOLANA_EXPLORER = 'https://explorer.solana.com/tx'
// Usage:
href={`${SOLANA_EXPLORER}/${hash}?cluster=devnet`}
```

In `BalanceTrustHistoryPanel.tsx`, replace the inline link:
```typescript
// Before:
href={`https://sepolia.basescan.org/tx/${e.tx_hash}`}
// After:
href={`https://explorer.solana.com/tx/${e.tx_hash}?cluster=devnet`}
```

- [ ] **Step 2: Update DevPanel.tsx**

- Replace `import { signChallengePermit } from '../lib/permit'` → `import { signJoinChallenge } from '../lib/sign-challenge'`
- Remove `import type { Hex } from 'viem'`
- Replace `import { getDevWalletAddress } from '../lib/x402'` — update call signature (base64 key instead of Hex)
- Replace Permit signing flow (~15 lines) with Solana transaction signing
- Replace `placeholder="0x..."` → `placeholder="So1ana..."`
- Replace `NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS` → `NEXT_PUBLIC_ESCROW_PROGRAM_ID`
- Replace any basescan explorer links in DevPanel

- [ ] **Step 3: Update address display in ChallengePanel, LeaderboardTable, ProfileView**

Ensure address truncation works for Solana Base58 (44 chars). Existing `wallet.slice(0, 6)...wallet.slice(-4)` pattern works for Base58 too, just remove any `0x` prefix assumptions.

- [ ] **Step 4: Remove all remaining viem imports**

Search all components for `from 'viem'` and remove.

- [ ] **Step 5: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Successful build

- [ ] **Step 6: Commit**

```bash
git add frontend/components/
git commit -m "feat: update frontend components for Solana (explorer links, address format)"
```

---

## Task 17: 最终测试验证

> Note: Test mock updates have been integrated into Tasks 4, 6, 7, 8 alongside each service rewrite. This task is a final sweep.

**Files:**
- Verify: all test files

- [ ] **Step 1: Search for any remaining web3/EVM references in tests**

Run: `grep -r "web3\|Web3\|0x036C\|basescan\|eip155\|base_sepolia\|from_key" tests/`
Expected: No matches (all replaced in earlier tasks)

- [ ] **Step 2: Run full backend test suite**

Run: `pytest tests/ -v`
Expected: All 252+ tests pass

- [ ] **Step 3: Fix any remaining failures**

If any tests fail, update the mock targets/signatures to match the new Solana service APIs.

- [ ] **Step 4: Commit if any fixes were needed**

```bash
git add tests/
git commit -m "test: final sweep of backend test mocks for Solana"
```

---

## Task 18: 清理 EVM 代码 + 更新文档

**Files:**
- Delete: `contracts/` directory
- Modify: `CLAUDE.md`

- [ ] **Step 1: Delete EVM contracts directory**

```bash
rm -rf contracts/
```

- [ ] **Step 2: Update CLAUDE.md**

Replace all EVM-specific content:
- Commands section: add `anchor build`, `anchor test`
- Environment variables: update table to Solana vars
- Architecture: replace web3.py references with solana-py
- ChallengeEscrow section: update to Anchor program description
- x402 payment flow: update to Solana transaction signing

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v && cd frontend && npm test`
Expected: All backend + frontend tests pass

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove EVM contracts, update CLAUDE.md for Solana"
```

- [ ] **Step 5: Push branch**

```bash
git push origin solana-x402
```
