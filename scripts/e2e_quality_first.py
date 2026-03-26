"""E2E test: quality_first full flow (publish → submit → deadline → scoring → challenge → arbitration → settle)."""

import base64, json, os, struct, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent / "frontend" / ".env.local")

import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address
from solana.rpc.api import Client

BASE_URL = "http://localhost:8000"
USDC_MINT = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
PLATFORM_WALLET = os.environ["PLATFORM_WALLET"]
kp = Keypair.from_bytes(
    base64.b64decode(os.environ["NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY"])
)
pay_to = Pubkey.from_string(PLATFORM_WALLET)
from_ata = get_associated_token_address(kp.pubkey(), USDC_MINT)
to_ata = get_associated_token_address(pay_to, USDC_MINT)


def sign_x402(amount_usdc):
    amount = int(amount_usdc * 1e6)
    data = struct.pack("<BQB", 12, amount, 6)
    ix = Instruction(
        program_id=Pubkey.from_string(str(TOKEN_PROGRAM_ID)),
        accounts=[
            AccountMeta(pubkey=from_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=USDC_MINT, is_signer=False, is_writable=False),
            AccountMeta(pubkey=to_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=kp.pubkey(), is_signer=True, is_writable=False),
        ],
        data=bytes(data),
    )
    sol_client = Client("https://api.devnet.solana.com")
    blockhash = sol_client.get_latest_blockhash().value.blockhash
    msg = Message.new_with_blockhash([ix], kp.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([kp], blockhash)
    tx_b64 = base64.b64encode(bytes(tx)).decode()
    payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "solana-devnet",
        "payload": {"serializedTransaction": tx_b64},
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def get_user_id(nickname):
    resp = httpx.get(f"{BASE_URL}/users", params={"nickname": nickname}, timeout=10)
    return resp.json()["id"]


def poll_task(task_id, target_status, timeout_s=300, interval=5):
    """Poll until task reaches target status or timeout."""
    for i in range(timeout_s // interval):
        try:
            resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
        except httpx.ReadTimeout:
            print(f"  [{(i+1)*interval}s] (timeout, retrying...)")
            continue
        t = resp.json()
        print(f"  [{(i+1)*interval}s] status={t['status']}", end="")
        subs = t.get("submissions", [])
        if subs:
            statuses = [s["status"] for s in subs]
            print(f", subs={statuses}", end="")
        print()
        if t["status"] == target_status:
            return t
        if t["status"] in ("closed", "voided"):
            print(f"  Task ended early: {t['status']}")
            return t
        time.sleep(interval)
    print(f"  TIMEOUT waiting for {target_status}")
    return httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10).json()


# ── Resolve user IDs ──
publisher_id = get_user_id("dev-publisher")
alice_id = get_user_id("Alice")
bob_id = get_user_id("Bob")
charlie_id = get_user_id("Charlie")
arbiter1_id = get_user_id("arbiter-alpha")
arbiter2_id = get_user_id("arbiter-beta")
arbiter3_id = get_user_id("arbiter-gamma")
print(
    f"Users: publisher={publisher_id[:8]}, alice={alice_id[:8]}, bob={bob_id[:8]}, charlie={charlie_id[:8]}"
)
print(f"Arbiters: {arbiter1_id[:8]}, {arbiter2_id[:8]}, {arbiter3_id[:8]}")

# ══════════════════════════════════════════════════════════
# Phase 1: Publish task
# ══════════════════════════════════════════════════════════
print("\n=== Phase 1: Publish quality_first task ===")
header = sign_x402(0.1)
deadline = (
    (datetime.now(timezone.utc) + timedelta(minutes=3))
    .isoformat()
    .replace("+00:00", "Z")
)
resp = httpx.post(
    f"{BASE_URL}/tasks",
    json={
        "title": "E2E Quality First: Solana Consensus",
        "description": "Write a comprehensive analysis of Solana consensus mechanism covering PoH, Tower BFT, Turbine, and Gulf Stream.",
        "type": "quality_first",
        "bounty": 0.1,
        "acceptance_criteria": [
            "Must cover Proof of History (PoH)",
            "Must cover Tower BFT",
            "Must cover Turbine block propagation",
            "Must cover Gulf Stream",
            "Minimum 200 words",
        ],
        "deadline": deadline,
        "challenge_duration": 60,  # 60s challenge window for testing
        "publisher_id": publisher_id,
    },
    headers={"X-PAYMENT": header},
    timeout=60,
)
print(f"Response: {resp.status_code}")
if resp.status_code not in (200, 201):
    print(resp.text[:500])
    raise SystemExit(1)
task = resp.json()
task_id = task["id"]
print(f"Task: {task_id}, status={task['status']}, deadline={deadline}")

# Wait for dimensions
print("\nWaiting for dimensions...")
for i in range(24):
    time.sleep(5)
    try:
        r = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
        dims = r.json().get("scoring_dimensions", [])
        if dims:
            print(f"  [{(i+1)*5}s] {len(dims)} dimensions generated")
            break
        print(f"  [{(i+1)*5}s] waiting...")
    except httpx.ReadTimeout:
        print(f"  [{(i+1)*5}s] (timeout, retrying...)")

# ══════════════════════════════════════════════════════════
# Phase 2: Multiple workers submit
# ══════════════════════════════════════════════════════════
print("\n=== Phase 2: Workers submit ===")

ALICE_CONTENT = (
    "Solana's consensus architecture combines four key innovations to achieve exceptional throughput. "
    "Proof of History (PoH) serves as a cryptographic clock, using sequential SHA-256 hashing to create "
    "a verifiable timeline of events. Each hash incorporates the previous output, forming an append-only "
    "sequence that proves time has elapsed without requiring validator communication about ordering. "
    "Tower BFT builds on this foundation as Solana's PBFT-like consensus mechanism. Validators vote on "
    "PoH slots rather than coordinating timestamps, reducing message complexity from O(n²) to O(n). "
    "Votes carry exponentially increasing lockout periods, creating strong finality guarantees. "
    "Turbine handles block propagation by breaking data into smaller packets distributed through a "
    "tree-like structure inspired by BitTorrent. This enables efficient data dissemination across thousands "
    "of validators without overwhelming network bandwidth. Gulf Stream pushes transaction forwarding to "
    "the network edge, allowing validators to begin executing transactions before the current block is "
    "finalized. This pipeline approach reduces confirmation times and memory pressure on validators. "
    "Together, these mechanisms enable Solana to process over 4,000 TPS with 400ms block times."
)

BOB_CONTENT = (
    "Solana uses several technologies for consensus. Proof of History creates timestamps using hashing. "
    "Tower BFT is the consensus algorithm that uses PoH as a clock. Validators vote on blocks and "
    "the network reaches agreement. Turbine breaks blocks into smaller pieces for faster propagation "
    "across the network. Gulf Stream forwards transactions to upcoming leaders. These four components "
    "work together to make Solana fast. PoH is particularly important because it solves the clock "
    "problem in distributed systems. Instead of validators needing to agree on time, PoH provides "
    "a cryptographic proof that time has passed between events. This reduces the overhead needed "
    "for consensus significantly. Tower BFT leverages this by having validators vote on PoH ticks "
    "rather than raw timestamps. The result is a blockchain that can handle thousands of transactions."
)

CHARLIE_CONTENT = (
    "Solana is a fast blockchain. It uses Proof of History which is a way to keep track of time. "
    "Tower BFT helps with consensus. Turbine sends blocks around. Gulf Stream helps too. "
    "Together they make Solana fast. Solana can do many transactions per second which makes it "
    "useful for many applications like DeFi and NFTs. The network has grown a lot recently."
)

for name, uid, content in [
    ("Alice", alice_id, ALICE_CONTENT),
    ("Bob", bob_id, BOB_CONTENT),
    ("Charlie", charlie_id, CHARLIE_CONTENT),
]:
    resp = httpx.post(
        f"{BASE_URL}/tasks/{task_id}/submissions",
        json={
            "worker_id": uid,
            "content": content,
        },
        timeout=30,
    )
    if resp.status_code in (200, 201):
        sub = resp.json()
        print(f"  {name}: submitted {sub['id'][:12]}, status={sub['status']}")
    else:
        print(f"  {name}: FAILED {resp.status_code} — {resp.text[:100]}")

# Wait for gate checks to complete
print("\nWaiting for gate checks (up to 120s)...")
time.sleep(10)
for i in range(36):
    time.sleep(5)
    try:
        r = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
    except httpx.ReadTimeout:
        print(f"  [{(i+1)*5+10}s] (timeout, retrying...)")
        continue
    subs = r.json().get("submissions", [])
    statuses = [
        (s.get("worker_nickname") or s["worker_id"][:8], s["status"]) for s in subs
    ]
    print(f"  [{(i+1)*5+10}s] {statuses}")
    if all(s[1] != "pending" for s in statuses):
        break

# Verify scores hidden during open phase
print("\nScores should be hidden (null) during open phase:")
r = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
for s in r.json().get("submissions", []):
    print(
        f"  {s.get('worker_nickname') or s['worker_id'][:8]}: score={s['score']}, status={s['status']}"
    )

# ══════════════════════════════════════════════════════════
# Phase 3: Wait for deadline → scoring → challenge_window
# ══════════════════════════════════════════════════════════
print("\n=== Phase 3: Deadline → Scoring → Challenge Window ===")
print("Waiting for scheduler to process deadline + batch scoring + escrow...")
t = poll_task(task_id, "challenge_window", timeout_s=360, interval=10)
print(f"\nTask status: {t['status']}")
print(f"Winner: {t.get('winner_submission_id')}")
print(f"Challenge window end: {t.get('challenge_window_end')}")
print(f"Escrow tx: {t.get('escrow_tx_hash')}")

if t["status"] != "challenge_window":
    print("ERROR: Did not reach challenge_window. Stopping.")
    raise SystemExit(1)

winner_sub_id = t["winner_submission_id"]
print("\nScores now visible:")
for s in t.get("submissions", []):
    print(
        f"  {s.get('worker_nickname') or s['worker_id'][:8]}: score={s['score']}, status={s['status']}"
    )
    if s["id"] == winner_sub_id:
        winner_worker = s["worker_id"]

# ══════════════════════════════════════════════════════════
# Phase 4: Challenge (skip for simplicity — let window expire)
# ══════════════════════════════════════════════════════════
print("\n=== Phase 4: Challenge window (60s, no challengers) ===")
print("Letting challenge window expire without challenges...")
t = poll_task(task_id, "closed", timeout_s=300, interval=10)

if t["status"] == "arbitrating":
    # ══════════════════════════════════════════════════════════
    # Phase 5: Arbitration (if needed)
    # ══════════════════════════════════════════════════════════
    print("\n=== Phase 5: Arbitration ===")
    print("Submitting jury votes...")
    for arbiter_name, arbiter_id in [
        ("arbiter-alpha", arbiter1_id),
        ("arbiter-beta", arbiter2_id),
        ("arbiter-gamma", arbiter3_id),
    ]:
        resp = httpx.post(
            f"{BASE_URL}/tasks/{task_id}/jury-vote",
            json={
                "arbiter_user_id": arbiter_id,
                "winner_submission_id": winner_sub_id,
                "malicious_submission_ids": [],
                "feedback": f"Vote from {arbiter_name}: winner submission is best",
            },
            timeout=30,
        )
        print(f"  {arbiter_name}: {resp.status_code} — {resp.text[:100]}")

    print("\nWaiting for resolution...")
    t = poll_task(task_id, "closed", timeout_s=180, interval=10)

# ══════════════════════════════════════════════════════════
# Final Status
# ══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("=== FINAL STATUS ===")
print("=" * 60)
r = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
t = r.json()
print(f"Task status: {t['status']}")
print(f"Winner: {t['winner_submission_id']}")
print(f"Payout status: {t['payout_status']}")
print(f"Payout tx: {t.get('payout_tx_hash')}")
print(f"Payout amount: {t.get('payout_amount')}")
print(f"Escrow tx: {t.get('escrow_tx_hash')}")

for s in t.get("submissions", []):
    nick = s.get("worker_nickname") or s["worker_id"][:8]
    winner = " *** WINNER ***" if s["id"] == t["winner_submission_id"] else ""
    print(f"\n  {nick}: score={s['score']}, status={s['status']}{winner}")

# Check trust events
print("\n--- Trust Events ---")
for name, uid in [("Alice", alice_id), ("Bob", bob_id), ("Publisher", publisher_id)]:
    resp = httpx.get(f"{BASE_URL}/users/{uid}", timeout=30)
    if resp.status_code == 200:
        u = resp.json()
        print(f"  {name}: trust={u['trust_score']}, tier={u['trust_tier']}")

print("\nDone!")
