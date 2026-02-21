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
            "name": "USD Coin",
            "version": "2",
        },
    }


def _facilitator_verify(payment_header: str, requirements: dict) -> dict:
    """Call the x402 facilitator to verify a payment. Separated for easy mocking."""
    try:
        decoded = json.loads(base64.b64decode(payment_header))
        resp = httpx.post(
            f"{FACILITATOR_URL}/verify",
            json={"paymentPayload": decoded, "paymentRequirements": requirements},
            timeout=30,
            follow_redirects=True,
        )
        data = resp.json()
        return {"valid": data.get("isValid", False), "tx_hash": data.get("payer")}
    except Exception:
        return {"valid": False, "tx_hash": None}


def verify_payment(payment_header: str | None, bounty: float) -> dict:
    """Verify an x402 payment header for a given bounty amount."""
    if not payment_header:
        return {"valid": False, "tx_hash": None}
    requirements = build_payment_requirements(bounty)
    return _facilitator_verify(payment_header, requirements)
