import os
import json
import base64
import struct

from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solana.rpc.api import Client
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address

SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
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


def _verify_and_settle(payment_header: str, expected_amount: int) -> dict:
    """Decode x402 header, verify SPL Token transfer, simulate, and submit on-chain."""
    try:
        decoded = json.loads(base64.b64decode(payment_header))
        payload = decoded.get("payload", {})
        # Support both field names
        tx_b64 = payload.get("transaction") or payload.get("serializedTransaction")
        if not tx_b64:
            return {
                "valid": False,
                "tx_hash": None,
                "reason": "no transaction in payload",
            }

        tx_bytes = base64.b64decode(tx_b64)
        tx = Transaction.from_bytes(tx_bytes)

        # Derive expected recipient ATA
        platform_pubkey = Pubkey.from_string(PLATFORM_WALLET)
        usdc_mint = Pubkey.from_string(USDC_MINT)
        token_program = Pubkey.from_string(str(TOKEN_PROGRAM_ID))
        expected_ata = get_associated_token_address(platform_pubkey, usdc_mint)

        # Verify SPL Token transfer instruction
        valid_transfer = False
        transfer_amount = 0

        for ix in tx.message.instructions:
            program_idx = ix.program_id_index
            program_id = tx.message.account_keys[program_idx]
            if program_id != token_program:
                continue

            ix_data = bytes(ix.data)
            if len(ix_data) < 1:
                continue

            ix_type = ix_data[0]

            # Type 3: Transfer (amount at bytes 1-8, u64 LE)
            if ix_type == 3 and len(ix_data) >= 9:
                transfer_amount = struct.unpack("<Q", ix_data[1:9])[0]
                if len(ix.accounts) >= 2:
                    dest_key = tx.message.account_keys[ix.accounts[1]]
                    if dest_key == expected_ata and transfer_amount >= expected_amount:
                        valid_transfer = True
                        break

            # Type 12: TransferChecked (amount at bytes 1-8, decimals at byte 9)
            if ix_type == 12 and len(ix_data) >= 10:
                transfer_amount = struct.unpack("<Q", ix_data[1:9])[0]
                if len(ix.accounts) >= 3:
                    # TransferChecked: [source, mint, dest, authority]
                    dest_key = tx.message.account_keys[ix.accounts[2]]
                    if dest_key == expected_ata and transfer_amount >= expected_amount:
                        valid_transfer = True
                        break

        if not valid_transfer:
            reason = (
                f"transfer amount {transfer_amount} < expected {expected_amount}"
                if transfer_amount > 0
                else "no valid SPL Token transfer instruction found"
            )
            return {"valid": False, "tx_hash": None, "reason": reason}

        print(
            f"[x402] Valid USDC transfer: {transfer_amount / 1e6} USDC to {expected_ata}",
            flush=True,
        )

        # Simulate transaction
        client = Client(SOLANA_RPC_URL)
        sim = client.simulate_transaction(tx)
        if sim.value.err:
            print(f"[x402] Simulation failed: {sim.value.err}", flush=True)
            return {
                "valid": False,
                "tx_hash": None,
                "reason": f"simulation failed: {sim.value.err}",
            }

        print("[x402] Simulation passed, submitting on-chain...", flush=True)

        # Submit on-chain
        sig_resp = client.send_raw_transaction(tx_bytes)
        signature = str(sig_resp.value)
        print(f"[x402] Transaction submitted: {signature}", flush=True)

        # Confirm
        client.confirm_transaction(sig_resp.value, commitment="confirmed")
        print(f"[x402] Transaction confirmed: {signature}", flush=True)

        return {"valid": True, "tx_hash": signature}

    except Exception as e:
        print(f"[x402] exception: {e}", flush=True)
        return {"valid": False, "tx_hash": None, "reason": str(e)}


def verify_payment(payment_header: str | None, bounty: float) -> dict:
    """Verify an x402 payment header for a given bounty amount."""
    if not payment_header:
        return {"valid": False, "tx_hash": None}
    expected_amount = int(bounty * 1e6)
    return _verify_and_settle(payment_header, expected_amount)
