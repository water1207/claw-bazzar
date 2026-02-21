import os
import httpx

FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "0x0000000000000000000000000000000000000000")
X402_NETWORK = os.environ.get("X402_NETWORK", "base-sepolia")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")


def build_payment_requirements(bounty: float) -> dict:
    """Build x402 payment requirements for a given bounty amount."""
    return {
        "amount": str(bounty),
        "network": X402_NETWORK,
        "asset": USDC_CONTRACT,
        "pay_to": PLATFORM_WALLET,
    }


def _facilitator_verify(payment_header: str, requirements: dict) -> dict:
    """Call the x402 facilitator to verify a payment. Separated for easy mocking."""
    try:
        resp = httpx.post(
            f"{FACILITATOR_URL}/verify",
            json={"payment": payment_header, "requirements": requirements},
            timeout=30,
        )
        data = resp.json()
        return {"valid": data.get("valid", False), "tx_hash": data.get("tx_hash")}
    except Exception:
        return {"valid": False, "tx_hash": None}


def verify_payment(payment_header: str | None, bounty: float) -> dict:
    """Verify an x402 payment header for a given bounty amount."""
    if not payment_header:
        return {"valid": False, "tx_hash": None}
    requirements = build_payment_requirements(bounty)
    return _facilitator_verify(payment_header, requirements)
