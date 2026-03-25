"""E2E test: fastest_first full flow."""

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


# Resolve user IDs dynamically
def get_user_id(nickname):
    resp = httpx.get(f"{BASE_URL}/users", params={"nickname": nickname}, timeout=10)
    return resp.json()["id"]


publisher_id = get_user_id("dev-publisher")
alice_id = get_user_id("Alice")
print(f"Publisher: {publisher_id}, Alice: {alice_id}")

# Step 1: Create task
print("=== Step 1: Create fastest_first task ===")
header = sign_x402(1.0)
deadline = (
    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
)
resp = httpx.post(
    f"{BASE_URL}/tasks",
    json={
        "title": "E2E Fastest First #2",
        "description": "Explain Solana Proof of History mechanism in detail.",
        "type": "fastest_first",
        "bounty": 1.0,
        "threshold": 60,
        "acceptance_criteria": ["Explain PoH mechanism", "At least 100 words"],
        "deadline": deadline,
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
print(f"Task created: {task_id}, status={task['status']}")

# Wait for dimensions to generate
print("\nWaiting for dimension generation (up to 90s)...")
for i in range(18):
    time.sleep(5)
    resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10)
    dims = resp.json().get("scoring_dimensions", [])
    print(f"  [{(i+1)*5}s] dimensions: {len(dims)}")
    if len(dims) > 0:
        break
resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10)
dims = resp.json().get("scoring_dimensions", [])
print(f"Dimensions generated: {len(dims)}")
for d in dims:
    print(f"  - {d['dim_id']}: {d['name']} (weight={d['weight']})")

# Step 2: Alice submits
print("\n=== Step 2: Alice submits ===")
# alice_id already resolved above
resp = httpx.post(
    f"{BASE_URL}/tasks/{task_id}/submissions",
    json={
        "worker_id": alice_id,
        "content": (
            "Solana's Proof of History (PoH) is a cryptographic clock that creates a verifiable "
            "passage of time between events. It uses a sequential SHA-256 hash chain where each "
            "hash takes the previous output as input, creating an append-only sequence that proves "
            "time has elapsed. Validators can verify the sequence in parallel by checking hash "
            "segments independently. This eliminates the need for validators to communicate about "
            "ordering — they simply verify the PoH sequence. The PoH generator runs continuously, "
            "timestamping transactions as they arrive. Combined with Tower BFT consensus, validators "
            "vote on PoH slots rather than raw timestamps, reducing communication overhead from "
            "O(n^2) to O(n). This enables Solana to achieve 400ms block times and process thousands "
            "of transactions per second, as the ordering problem is solved before consensus begins."
        ),
    },
    timeout=30,
)
sub = resp.json()
sub_id = sub["id"]
print(f"Submission: {sub_id}, status={sub['status']}")

# Step 3: Wait for Oracle scoring
print("\nWaiting for Oracle scoring (up to 120s)...")
for i in range(24):
    time.sleep(5)
    resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10)
    t = resp.json()
    subs = t.get("submissions", [])
    sub_status = subs[0]["status"] if subs else "unknown"
    print(
        f"  [{(i+1)*5}s] task={t['status']}, sub={sub_status}, score={subs[0].get('score') if subs else None}"
    )
    if t["status"] != "open" or sub_status == "scored":
        break

# Final status
print("\n=== Final Status ===")
resp = httpx.get(f"{BASE_URL}/tasks/{task_id}", timeout=10)
t = resp.json()
print(f"Task status: {t['status']}")
print(f"Winner: {t['winner_submission_id']}")
print(f"Payout status: {t['payout_status']}")
print(f"Payout tx: {t.get('payout_tx_hash')}")
print(f"Payout amount: {t.get('payout_amount')}")
for s in t.get("submissions", []):
    print(f"\nSubmission {s['id'][:12]}:")
    print(f"  status={s['status']}, score={s['score']}")
    fb = json.loads(s.get("oracle_feedback") or "{}")
    print(f"  feedback type={fb.get('type')}")
    if "dimension_scores" in fb:
        for dim_id, ds in fb["dimension_scores"].items():
            print(f"    {dim_id}: band={ds.get('band')}, score={ds.get('score')}")
