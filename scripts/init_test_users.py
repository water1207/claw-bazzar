"""
Initialize test users via API calls.
Registers all dev wallets, sets trust tiers, and marks arbiters.

Usage: python scripts/init_test_users.py [--base-url http://localhost:8000]
"""

import base64
import sys

import httpx
from pathlib import Path
from solders.keypair import Keypair

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

# Parse wallet keys from frontend/.env.local
env_local = Path(__file__).parent.parent / "frontend" / ".env.local"
wallets = {}
for line in env_local.read_text().splitlines():
    if "_WALLET_KEY=" in line and line.startswith("NEXT_PUBLIC_DEV_"):
        name, val = line.split("=", 1)
        role_key = name.replace("NEXT_PUBLIC_DEV_", "").replace("_WALLET_KEY", "")
        key_bytes = base64.b64decode(val)
        kp = Keypair.from_bytes(key_bytes)
        wallets[role_key] = str(kp.pubkey())

# User definitions: (env_key, nickname, role, trust_score, is_arbiter)
USERS = [
    ("PUBLISHER", "dev-publisher", "publisher", 850, False),
    ("WORKER", "Alice", "worker", 850, False),  # S-tier
    ("WORKER2", "Bob", "worker", 550, False),  # A-tier
    ("WORKER3", "Charlie", "worker", 350, False),  # B-tier
    ("WORKER4", "Diana", "worker", 400, False),  # B-tier
    ("WORKER5", "Ethan", "worker", 200, False),  # C-tier (banned)
    ("ARBITER1", "arbiter-alpha", "worker", 850, True),  # S-tier arbiter
    ("ARBITER2", "arbiter-beta", "worker", 850, True),  # S-tier arbiter
    ("ARBITER3", "arbiter-gamma", "worker", 850, True),  # S-tier arbiter
]

client = httpx.Client(base_url=BASE_URL, timeout=10)

print(f"Base URL: {BASE_URL}\n")

for env_key, nickname, role, trust_score, is_arbiter in USERS:
    wallet = wallets.get(env_key)
    if not wallet:
        print(f"  SKIP {nickname}: no wallet key found for {env_key}")
        continue

    # 1. Register user
    resp = client.post(
        "/users",
        json={
            "nickname": nickname,
            "wallet": wallet,
            "role": role,
        },
    )
    if resp.status_code in (200, 201):
        user_id = resp.json()["id"]
        print(f"  Registered {nickname} ({wallet[:12]}...): {user_id}")
    else:
        print(f"  WARN {nickname}: register returned {resp.status_code} — {resp.text}")
        continue

    # 2. Set trust score + arbiter flag
    patch_data = {"score": trust_score}
    if is_arbiter:
        patch_data["is_arbiter"] = True
        patch_data["github_id"] = f"gh-{nickname}"
    resp = client.patch(f"/internal/users/{user_id}/trust", json=patch_data)
    if resp.status_code == 200:
        data = resp.json()
        print(
            f"    → trust={data['trust_score']}, tier={data['trust_tier']}, arbiter={data.get('is_arbiter', False)}"
        )
    else:
        print(f"    → WARN: set trust returned {resp.status_code} — {resp.text}")

print("\nDone!")
print(f"\n{'Nickname':<20} {'Wallet':<48} {'Trust':>6} {'Tier':>5} {'Arbiter':>8}")
print("-" * 90)
for env_key, nickname, role, trust_score, is_arbiter in USERS:
    wallet = wallets.get(env_key, "???")
    tier = (
        "S"
        if trust_score >= 800
        else "A" if trust_score >= 500 else "B" if trust_score >= 300 else "C"
    )
    print(
        f"{nickname:<20} {wallet:<48} {trust_score:>6} {tier:>5} {'Yes' if is_arbiter else 'No':>8}"
    )
