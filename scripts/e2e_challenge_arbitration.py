"""E2E test: Challenge + Arbitration scenarios (Tasks 9-12).

Scenario A — PW wins:      2 arbiters vote for original winner, 1 for challenger
Scenario B — Challenger wins: 2 arbiters vote for challenger, 1 for original winner
Scenario C — Malicious VOID:  ≥2 arbiters tag winner as malicious → task voided
"""

import base64, json, os, struct, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent / "frontend" / ".env.local")

import httpx

# Disable proxy for localhost; fix Windows GBK encoding
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

http_client = httpx.Client(timeout=30, trust_env=False)

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


# ── Helpers ──────────────────────────────────────────────


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
    for attempt in range(5):
        try:
            resp = http_client.get(
                f"{BASE_URL}/users", params={"nickname": nickname}, timeout=60
            )
            data = resp.json()
            if "id" in data:
                return data["id"]
            print(f"  get_user_id({nickname}) unexpected: {data}")
        except (httpx.ReadTimeout, httpx.ConnectError) as e:
            print(
                f"  get_user_id({nickname}) {e.__class__.__name__}, retry {attempt+1}..."
            )
        time.sleep(2)
    raise RuntimeError(f"Cannot resolve user {nickname}")


def poll_task(task_id, target_status, timeout_s=360, interval=10):
    """Poll until task reaches target status or timeout."""
    for i in range(timeout_s // interval):
        try:
            resp = http_client.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
        except httpx.ReadTimeout:
            print(f"  [{(i+1)*interval}s] (timeout, retrying...)")
            continue
        t = resp.json()
        subs = t.get("submissions", [])
        sub_info = ""
        if subs:
            sub_info = f", subs=[{', '.join(s['status'] for s in subs)}]"
        print(f"  [{(i+1)*interval}s] status={t['status']}{sub_info}")
        if t["status"] == target_status:
            return t
        if t["status"] in ("closed", "voided") and target_status not in (
            "closed",
            "voided",
        ):
            print(f"  Task ended early: {t['status']}")
            return t
        time.sleep(interval)
    print(f"  TIMEOUT waiting for {target_status}")
    return http_client.get(f"{BASE_URL}/tasks/{task_id}", timeout=10).json()


def publish_task(title, bounty=0.1, deadline_minutes=3, challenge_duration=60):
    """Publish a quality_first task and wait for dimensions."""
    header = sign_x402(bounty)
    deadline = (
        (datetime.now(timezone.utc) + timedelta(minutes=deadline_minutes))
        .isoformat()
        .replace("+00:00", "Z")
    )
    resp = http_client.post(
        f"{BASE_URL}/tasks",
        json={
            "title": title,
            "description": "Write a comprehensive analysis of Solana consensus mechanism.",
            "type": "quality_first",
            "bounty": bounty,
            "acceptance_criteria": [
                "Must cover Proof of History (PoH)",
                "Must cover Tower BFT",
                "Must cover Turbine block propagation",
                "Must cover Gulf Stream",
                "Minimum 200 words",
            ],
            "deadline": deadline,
            "challenge_duration": challenge_duration,
            "publisher_id": publisher_id,
        },
        headers={"X-PAYMENT": header},
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        print(f"  FAILED: {resp.status_code} — {resp.text[:300]}")
        raise SystemExit(1)
    task = resp.json()
    print(f"  Task: {task['id'][:12]}, deadline={deadline}")

    # Wait for dimensions
    for i in range(24):
        time.sleep(5)
        try:
            r = http_client.get(f"{BASE_URL}/tasks/{task['id']}", timeout=30)
            dims = r.json().get("scoring_dimensions", [])
            if dims:
                print(f"  [{(i+1)*5}s] {len(dims)} dimensions generated")
                break
            print(f"  [{(i+1)*5}s] waiting for dimensions...")
        except httpx.ReadTimeout:
            print(f"  [{(i+1)*5}s] (timeout, retrying...)")
    return task


def submit_workers(task_id, workers):
    """Submit content for Alice and Bob."""
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
    contents = {"Alice": ALICE_CONTENT, "Bob": BOB_CONTENT}
    for name, uid in workers:
        resp = http_client.post(
            f"{BASE_URL}/tasks/{task_id}/submissions",
            json={"worker_id": uid, "content": contents[name]},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            sub = resp.json()
            print(f"  {name}: submitted {sub['id'][:12]}")
        else:
            print(f"  {name}: FAILED {resp.status_code} — {resp.text[:100]}")

    # Wait for gate checks
    print("  Waiting for gate checks...")
    for i in range(30):
        time.sleep(5)
        try:
            r = http_client.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
        except httpx.ReadTimeout:
            continue
        subs = r.json().get("submissions", [])
        statuses = [
            (s.get("worker_nickname", s["worker_id"][:8]), s["status"]) for s in subs
        ]
        print(f"  [{(i+1)*5}s] {statuses}")
        if all(s[1] != "pending" for s in statuses):
            break


def file_challenge(task_id, challenger_sub_id, reason):
    """File a challenge (without on-chain deposit to conserve USDC)."""
    resp = http_client.post(
        f"{BASE_URL}/tasks/{task_id}/challenges",
        json={
            "challenger_submission_id": challenger_sub_id,
            "reason": reason,
        },
        timeout=30,
    )
    if resp.status_code in (200, 201):
        c = resp.json()
        print(f"  Challenge filed: {c['id'][:12]}, status={c['status']}")
        return c
    else:
        print(f"  Challenge FAILED: {resp.status_code} — {resp.text[:200]}")
        return None


def submit_jury_votes(task_id, votes):
    """Submit jury votes.
    votes: list of dicts with arbiter_user_id, winner_submission_id,
           and optionally malicious_submission_ids, feedback
    """
    for v in votes:
        resp = http_client.post(
            f"{BASE_URL}/tasks/{task_id}/jury-vote",
            json=v,
            timeout=30,
        )
        name = v.get("_name", v["arbiter_user_id"][:8])
        if resp.status_code in (200, 201):
            print(f"  {name}: voted for {v['winner_submission_id'][:8]}")
            if v.get("malicious_submission_ids"):
                print(
                    f"    tagged malicious: {[m[:8] for m in v['malicious_submission_ids']]}"
                )
        else:
            print(f"  {name}: FAILED {resp.status_code} — {resp.text[:200]}")


def print_final_status(task_id, scenario_label):
    """Print final task status with all details."""
    # Wait for payout to settle (scheduler may still be processing contract call)
    for _ in range(6):
        r = http_client.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
        t = r.json()
        if t.get("payout_status") not in (None, "pending"):
            break
        if t["status"] == "voided":
            break
        time.sleep(5)
    r = http_client.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
    t = r.json()
    print(f"\n{'=' * 60}")
    print(f"  {scenario_label} — FINAL STATUS")
    print(f"{'=' * 60}")
    print(f"  Task status:  {t['status']}")
    print(f"  Winner:       {t.get('winner_submission_id', 'N/A')}")
    print(f"  Payout status:{t.get('payout_status', 'N/A')}")
    print(f"  Payout tx:    {t.get('payout_tx_hash', 'N/A')}")
    print(f"  Payout amount:{t.get('payout_amount', 'N/A')}")
    print(f"  Escrow tx:    {t.get('escrow_tx_hash', 'N/A')}")

    for s in t.get("submissions", []):
        nick = s.get("worker_nickname") or s["worker_id"][:8]
        winner = " *** WINNER ***" if s["id"] == t.get("winner_submission_id") else ""
        print(f"  {nick}: score={s['score']}, status={s['status']}{winner}")

    # Trust events
    print("\n  --- Trust Events ---")
    for name, uid in [
        ("Alice", alice_id),
        ("Bob", bob_id),
        ("Publisher", publisher_id),
    ]:
        resp = http_client.get(f"{BASE_URL}/users/{uid}", timeout=30)
        if resp.status_code == 200:
            u = resp.json()
            print(f"  {name}: trust={u['trust_score']}, tier={u['trust_tier']}")

    # Jury ballots
    try:
        resp = http_client.get(f"{BASE_URL}/tasks/{task_id}/jury-ballots", timeout=30)
        if resp.status_code == 200:
            ballots = resp.json()
            print("\n  --- Jury Ballots ---")
            for b in ballots:
                nick = b.get("arbiter_nickname", b.get("arbiter_user_id", "?")[:8])
                winner = b.get("winner_submission_id", "?")
                winner_short = winner[:8] if winner else "N/A"
                coh = b.get("coherence_status", "?")
                tags = b.get("malicious_tags", [])
                print(
                    f"  {nick}: voted={winner_short}, coherence={coh}, tags={len(tags)}"
                )
    except Exception:
        pass

    return t


# ── Resolve user IDs ──
publisher_id = get_user_id("dev-publisher")
alice_id = get_user_id("Alice")
bob_id = get_user_id("Bob")
arbiter1_id = get_user_id("arbiter-alpha")
arbiter2_id = get_user_id("arbiter-beta")
arbiter3_id = get_user_id("arbiter-gamma")
print(f"Users: publisher={publisher_id[:8]}, alice={alice_id[:8]}, bob={bob_id[:8]}")
print(f"Arbiters: {arbiter1_id[:8]}, {arbiter2_id[:8]}, {arbiter3_id[:8]}")


# ══════════════════════════════════════════════════════════
# SCENARIO A: PW wins (original winner upheld)
# ══════════════════════════════════════════════════════════
def run_scenario_a():
    print("\n" + "█" * 60)
    print("█  SCENARIO A: PW Wins (Original Winner Upheld)")
    print("█" * 60)

    # Phase 1: Publish
    print("\n--- Publish task ---")
    task = publish_task("E2E Scenario A: PW Wins", bounty=0.1)
    task_id = task["id"]

    # Phase 2: Submit
    print("\n--- Workers submit ---")
    submit_workers(task_id, [("Alice", alice_id), ("Bob", bob_id)])

    # Phase 3: Wait for challenge_window
    print("\n--- Waiting for deadline → scoring → challenge_window ---")
    t = poll_task(task_id, "challenge_window", timeout_s=420, interval=10)
    if t["status"] != "challenge_window":
        print(f"ERROR: Did not reach challenge_window (got {t['status']})")
        return False

    winner_sub_id = t["winner_submission_id"]
    print(f"  Winner (PW): {winner_sub_id[:12]}")

    # Find Bob's submission (the challenger)
    bob_sub = next(
        s
        for s in t["submissions"]
        if s.get("worker_nickname") == "Bob" or s["worker_id"] == bob_id
    )
    bob_sub_id = bob_sub["id"]
    print(f"  Bob's sub:   {bob_sub_id[:12]}")

    # Phase 4: Bob challenges
    print("\n--- Bob files challenge ---")
    challenge = file_challenge(
        task_id, bob_sub_id, "I believe my analysis is more comprehensive"
    )
    if not challenge:
        return False

    # Phase 5: Wait for challenge_window → arbitrating
    print("\n--- Waiting for challenge_window → arbitrating ---")
    t = poll_task(task_id, "arbitrating", timeout_s=300, interval=10)
    if t["status"] != "arbitrating":
        print(f"ERROR: Did not reach arbitrating (got {t['status']})")
        return False

    # Phase 6: Jury votes — 2 for PW (Alice), 1 for challenger (Bob)
    print("\n--- Jury votes: 2 for PW, 1 for challenger ---")
    submit_jury_votes(
        task_id,
        [
            {
                "arbiter_user_id": arbiter1_id,
                "winner_submission_id": winner_sub_id,
                "feedback": "Original winner is clearly better",
                "_name": "arbiter-alpha",
            },
            {
                "arbiter_user_id": arbiter2_id,
                "winner_submission_id": winner_sub_id,
                "feedback": "PW submission is more thorough",
                "_name": "arbiter-beta",
            },
            {
                "arbiter_user_id": arbiter3_id,
                "winner_submission_id": bob_sub_id,
                "feedback": "Challenger has valid points",
                "_name": "arbiter-gamma",
            },
        ],
    )

    # Phase 7: Wait for resolution
    print("\n--- Waiting for resolution → closed ---")
    t = poll_task(task_id, "closed", timeout_s=300, interval=10)

    result = print_final_status(task_id, "SCENARIO A: PW Wins")

    # Verify
    ok = True
    if result["status"] != "closed":
        print("  ❌ FAIL: Expected status=closed")
        ok = False
    if result.get("payout_status") != "paid":
        print(
            f"  ❌ FAIL: Expected payout_status=paid, got {result.get('payout_status')}"
        )
        ok = False
    if result.get("winner_submission_id") != winner_sub_id:
        print("  ❌ FAIL: Winner should still be original PW")
        ok = False
    print(f"\n  {'✅ SCENARIO A PASSED' if ok else '❌ SCENARIO A FAILED'}")
    return ok


# ══════════════════════════════════════════════════════════
# SCENARIO B: Challenger wins (PW overthrown)
# ══════════════════════════════════════════════════════════
def run_scenario_b():
    print("\n" + "█" * 60)
    print("█  SCENARIO B: Challenger Wins (PW Overthrown)")
    print("█" * 60)

    # Phase 1: Publish
    print("\n--- Publish task ---")
    task = publish_task("E2E Scenario B: Challenger Wins", bounty=0.1)
    task_id = task["id"]

    # Phase 2: Submit
    print("\n--- Workers submit ---")
    submit_workers(task_id, [("Alice", alice_id), ("Bob", bob_id)])

    # Phase 3: Wait for challenge_window
    print("\n--- Waiting for deadline → scoring → challenge_window ---")
    t = poll_task(task_id, "challenge_window", timeout_s=420, interval=10)
    if t["status"] != "challenge_window":
        print(f"ERROR: Did not reach challenge_window (got {t['status']})")
        return False

    winner_sub_id = t["winner_submission_id"]
    print(f"  Original Winner: {winner_sub_id[:12]}")

    # Find the non-winner submission (challenger)
    challenger_sub = next(s for s in t["submissions"] if s["id"] != winner_sub_id)
    challenger_sub_id = challenger_sub["id"]
    challenger_nick = challenger_sub.get(
        "worker_nickname", challenger_sub["worker_id"][:8]
    )
    print(f"  Challenger ({challenger_nick}): {challenger_sub_id[:12]}")

    # Phase 4: Challenge
    print(f"\n--- {challenger_nick} files challenge ---")
    challenge = file_challenge(
        task_id, challenger_sub_id, "My submission deserves to win"
    )
    if not challenge:
        return False

    # Phase 5: Wait for arbitrating
    print("\n--- Waiting for challenge_window → arbitrating ---")
    t = poll_task(task_id, "arbitrating", timeout_s=300, interval=10)
    if t["status"] != "arbitrating":
        print(f"ERROR: Did not reach arbitrating (got {t['status']})")
        return False

    # Phase 6: Jury votes — 2 for challenger, 1 for PW
    print(f"\n--- Jury votes: 2 for challenger ({challenger_nick}), 1 for PW ---")
    submit_jury_votes(
        task_id,
        [
            {
                "arbiter_user_id": arbiter1_id,
                "winner_submission_id": challenger_sub_id,
                "feedback": "Challenger's work is actually better",
                "_name": "arbiter-alpha",
            },
            {
                "arbiter_user_id": arbiter2_id,
                "winner_submission_id": challenger_sub_id,
                "feedback": "Challenger submission is more detailed",
                "_name": "arbiter-beta",
            },
            {
                "arbiter_user_id": arbiter3_id,
                "winner_submission_id": winner_sub_id,
                "feedback": "Original winner is fine",
                "_name": "arbiter-gamma",
            },
        ],
    )

    # Phase 7: Wait for resolution
    print("\n--- Waiting for resolution → closed ---")
    t = poll_task(task_id, "closed", timeout_s=300, interval=10)

    result = print_final_status(task_id, "SCENARIO B: Challenger Wins")

    # Verify: winner should have switched to challenger
    ok = True
    if result["status"] != "closed":
        print("  ❌ FAIL: Expected status=closed")
        ok = False
    if result.get("payout_status") != "paid":
        print(
            f"  ❌ FAIL: Expected payout_status=paid, got {result.get('payout_status')}"
        )
        ok = False
    if result.get("winner_submission_id") != challenger_sub_id:
        print(f"  ❌ FAIL: Winner should be challenger {challenger_sub_id[:12]}")
        ok = False
    else:
        print(f"  ✅ Winner correctly switched to challenger ({challenger_nick})")
    print(f"\n  {'✅ SCENARIO B PASSED' if ok else '❌ SCENARIO B FAILED'}")
    return ok


# ══════════════════════════════════════════════════════════
# SCENARIO C: Malicious VOID (≥2 arbiters tag winner)
# ══════════════════════════════════════════════════════════
def run_scenario_c():
    print("\n" + "█" * 60)
    print("█  SCENARIO C: Malicious VOID (PW tagged malicious)")
    print("█" * 60)

    # Phase 1: Publish
    print("\n--- Publish task ---")
    task = publish_task("E2E Scenario C: Malicious VOID", bounty=0.1)
    task_id = task["id"]

    # Phase 2: Submit
    print("\n--- Workers submit ---")
    submit_workers(task_id, [("Alice", alice_id), ("Bob", bob_id)])

    # Phase 3: Wait for challenge_window
    print("\n--- Waiting for deadline → scoring → challenge_window ---")
    t = poll_task(task_id, "challenge_window", timeout_s=420, interval=10)
    if t["status"] != "challenge_window":
        print(f"ERROR: Did not reach challenge_window (got {t['status']})")
        return False

    winner_sub_id = t["winner_submission_id"]
    print(f"  Winner (PW): {winner_sub_id[:12]}")

    # Find the non-winner submission (challenger)
    challenger_sub = next(s for s in t["submissions"] if s["id"] != winner_sub_id)
    challenger_sub_id = challenger_sub["id"]
    challenger_nick = challenger_sub.get(
        "worker_nickname", challenger_sub["worker_id"][:8]
    )
    print(f"  Challenger ({challenger_nick}): {challenger_sub_id[:12]}")

    # Phase 4: Challenge
    print(f"\n--- {challenger_nick} files challenge ---")
    challenge = file_challenge(
        task_id, challenger_sub_id, "The winning submission looks plagiarized"
    )
    if not challenge:
        return False

    # Phase 5: Wait for arbitrating
    print("\n--- Waiting for challenge_window → arbitrating ---")
    t = poll_task(task_id, "arbitrating", timeout_s=300, interval=10)
    if t["status"] != "arbitrating":
        print(f"ERROR: Did not reach arbitrating (got {t['status']})")
        return False

    # Phase 6: Jury votes — all 3 vote for challenger, 2 tag winner as malicious
    print(f"\n--- Jury votes: 3 for challenger, 2 tag PW winner as malicious ---")
    submit_jury_votes(
        task_id,
        [
            {
                "arbiter_user_id": arbiter1_id,
                "winner_submission_id": challenger_sub_id,
                "malicious_submission_ids": [winner_sub_id],
                "feedback": "Winner submission appears plagiarized",
                "_name": "arbiter-alpha",
            },
            {
                "arbiter_user_id": arbiter2_id,
                "winner_submission_id": challenger_sub_id,
                "malicious_submission_ids": [winner_sub_id],
                "feedback": "Agree, winner content is suspicious",
                "_name": "arbiter-beta",
            },
            {
                "arbiter_user_id": arbiter3_id,
                "winner_submission_id": challenger_sub_id,
                "feedback": "Challenger is better but winner isn't malicious",
                "_name": "arbiter-gamma",
            },
        ],
    )

    # Phase 7: Wait for resolution → voided
    print("\n--- Waiting for resolution → voided ---")
    t = poll_task(task_id, "voided", timeout_s=300, interval=10)

    result = print_final_status(task_id, "SCENARIO C: Malicious VOID")

    # Verify
    ok = True
    if result["status"] != "voided":
        print(f"  ❌ FAIL: Expected status=voided, got {result['status']}")
        ok = False
    else:
        print("  ✅ Task correctly voided (PW malicious detected)")
    if result.get("payout_status") == "paid":
        print("  ❌ FAIL: Should not have payout_status=paid for voided task")
        ok = False
    print(f"\n  {'✅ SCENARIO C PASSED' if ok else '❌ SCENARIO C FAILED'}")
    return ok


# ══════════════════════════════════════════════════════════
# Main: Run selected or all scenarios
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    scenarios = {
        "a": ("Scenario A: PW Wins", run_scenario_a),
        "b": ("Scenario B: Challenger Wins", run_scenario_b),
        "c": ("Scenario C: Malicious VOID", run_scenario_c),
    }

    selected = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if selected == "all":
        to_run = list(scenarios.values())
    elif selected in scenarios:
        to_run = [scenarios[selected]]
    else:
        print(f"Usage: {sys.argv[0]} [a|b|c|all]")
        raise SystemExit(1)

    results = {}
    for label, fn in to_run:
        try:
            results[label] = fn()
        except Exception as e:
            print(f"\n  ❌ {label} EXCEPTION: {e}")
            import traceback

            traceback.print_exc()
            results[label] = False

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for label, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {label}")
    print()

    if not all(results.values()):
        raise SystemExit(1)
