import os
import json
import base64

import httpx

FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "0x0000000000000000000000000000000000000000")
X402_NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")


def build_payment_requirements(bounty: float) -> dict:
    """Build x402 payment requirements for a given bounty amount."""
    return {
        "scheme": "exact",
        "network": X402_NETWORK,
        "asset": USDC_CONTRACT,
        "amount": str(int(bounty * 1e6)),
        "payTo": PLATFORM_WALLET,
        "maxTimeoutSeconds": 30,
        "extra": {
            "assetTransferMethod": "eip3009",
            "name": "USDC",
            "version": "2",
        },
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
