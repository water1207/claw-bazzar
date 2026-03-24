"""
Fund test wallets with SOL and devnet USDC.
Reads wallet keys from frontend/.env.local and transfers from platform wallet.
"""

import base64
import os
import json
import time
from pathlib import Path

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
from solana.rpc.api import Client
from spl.token.instructions import (
    get_associated_token_address,
    create_associated_token_account,
    transfer_checked,
    TransferCheckedParams,
)
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID

# Config
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
USDC_MINT = Pubkey.from_string(
    os.getenv("USDC_MINT", "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
)
USDC_DECIMALS = 6
SOL_AMOUNT = 500_000_000  # 0.5 SOL per wallet (in lamports)
USDC_AMOUNT = 100 * (10**USDC_DECIMALS)  # 100 USDC per wallet

# Load platform keypair from .env
env_path = Path(__file__).parent.parent / ".env"
platform_key_json = None
for line in env_path.read_text().splitlines():
    if line.startswith("PLATFORM_PRIVATE_KEY="):
        platform_key_json = line.split("=", 1)[1]
        break

if not platform_key_json:
    raise ValueError("PLATFORM_PRIVATE_KEY not found in .env")

platform_kp = Keypair.from_bytes(bytes(json.loads(platform_key_json)))
print(f"Platform wallet: {platform_kp.pubkey()}")

# Load test wallet keys from frontend/.env.local
env_local_path = Path(__file__).parent.parent / "frontend" / ".env.local"
wallets = {}
for line in env_local_path.read_text().splitlines():
    if "_WALLET_KEY=" in line and line.startswith("NEXT_PUBLIC_DEV_"):
        name, val = line.split("=", 1)
        role = name.replace("NEXT_PUBLIC_DEV_", "").replace("_WALLET_KEY", "")
        key_bytes = base64.b64decode(val)
        kp = Keypair.from_bytes(key_bytes)
        wallets[role] = kp

print(f"\nFound {len(wallets)} test wallets:")
for role, kp in wallets.items():
    print(f"  {role}: {kp.pubkey()}")

# Connect
client = Client(RPC_URL)

# Check platform SOL balance
resp = client.get_balance(platform_kp.pubkey())
platform_sol = resp.value
print(f"\nPlatform SOL balance: {platform_sol / 1e9:.4f} SOL")

# Check platform USDC balance
platform_ata = get_associated_token_address(platform_kp.pubkey(), USDC_MINT)
resp = client.get_token_account_balance(platform_ata)
if resp.value:
    platform_usdc = int(resp.value.amount)
    print(f"Platform USDC balance: {platform_usdc / 1e6:.2f} USDC")
else:
    platform_usdc = 0
    print("Platform has no USDC ATA yet")

# Transfer SOL to each wallet
print("\n--- Transferring SOL ---")
for role, kp in wallets.items():
    pubkey = kp.pubkey()
    bal = client.get_balance(pubkey).value
    if bal >= SOL_AMOUNT:
        print(f"  {role} ({pubkey}): already has {bal/1e9:.4f} SOL, skipping")
        continue

    ix = transfer(
        TransferParams(
            from_pubkey=platform_kp.pubkey(),
            to_pubkey=pubkey,
            lamports=SOL_AMOUNT,
        )
    )
    blockhash = client.get_latest_blockhash().value.blockhash
    msg = Message.new_with_blockhash([ix], platform_kp.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([platform_kp], blockhash)
    sig = client.send_transaction(tx).value
    print(f"  {role} ({pubkey}): sent 0.5 SOL, tx: {sig}")
    time.sleep(0.5)

# Transfer USDC to each wallet
if platform_usdc > 0:
    print("\n--- Transferring USDC ---")
    for role, kp in wallets.items():
        pubkey = kp.pubkey()
        dest_ata = get_associated_token_address(pubkey, USDC_MINT)

        # Check if ATA exists
        ata_info = client.get_account_info(dest_ata)
        if ata_info.value is None:
            # Create ATA (platform pays)
            create_ix = create_associated_token_account(
                payer=platform_kp.pubkey(),
                owner=pubkey,
                mint=USDC_MINT,
            )
            blockhash = client.get_latest_blockhash().value.blockhash
            msg = Message.new_with_blockhash(
                [create_ix], platform_kp.pubkey(), blockhash
            )
            tx = Transaction.new_unsigned(msg)
            tx.sign([platform_kp], blockhash)
            sig = client.send_transaction(tx).value
            print(f"  {role}: created USDC ATA, tx: {sig}")
            time.sleep(1)

        # Transfer USDC
        amount_to_send = min(USDC_AMOUNT, platform_usdc // len(wallets))
        if amount_to_send == 0:
            print(f"  {role}: insufficient USDC, skipping")
            continue

        transfer_ix = transfer_checked(
            TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=platform_ata,
                mint=USDC_MINT,
                dest=dest_ata,
                owner=platform_kp.pubkey(),
                amount=amount_to_send,
                decimals=USDC_DECIMALS,
            )
        )
        blockhash = client.get_latest_blockhash().value.blockhash
        msg = Message.new_with_blockhash([transfer_ix], platform_kp.pubkey(), blockhash)
        tx = Transaction.new_unsigned(msg)
        tx.sign([platform_kp], blockhash)
        sig = client.send_transaction(tx).value
        print(f"  {role} ({pubkey}): sent {amount_to_send/1e6:.2f} USDC, tx: {sig}")
        time.sleep(0.5)
else:
    print("\n--- Skipping USDC transfers (platform has no USDC) ---")
    print("To get devnet USDC, use the Circle faucet: https://faucet.circle.com/")

print("\n--- Final balances ---")
for role, kp in wallets.items():
    pubkey = kp.pubkey()
    sol_bal = client.get_balance(pubkey).value
    ata = get_associated_token_address(pubkey, USDC_MINT)
    usdc_resp = client.get_token_account_balance(ata)
    usdc_bal = int(usdc_resp.value.amount) if usdc_resp.value else 0
    print(f"  {role} ({pubkey}): {sol_bal/1e9:.4f} SOL, {usdc_bal/1e6:.2f} USDC")

print("\nDone!")
