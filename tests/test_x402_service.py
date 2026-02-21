"""Tests for the x402 payment service."""
from unittest.mock import patch


def test_build_payment_requirements():
    from app.services.x402 import build_payment_requirements

    result = build_payment_requirements(2.5)
    assert result["amount"] == "2.5"
    assert "network" in result
    assert "asset" in result
    assert "pay_to" in result


def test_verify_payment_valid():
    from app.services.x402 import verify_payment

    with patch(
        "app.services.x402._facilitator_verify",
        return_value={"valid": True, "tx_hash": "0xabc123"},
    ):
        result = verify_payment("some-payment-header", 1.0)
    assert result["valid"] is True
    assert result["tx_hash"] == "0xabc123"


def test_verify_payment_invalid():
    from app.services.x402 import verify_payment

    with patch(
        "app.services.x402._facilitator_verify",
        return_value={"valid": False, "tx_hash": None},
    ):
        result = verify_payment("bad-payment-header", 1.0)
    assert result["valid"] is False
    assert result["tx_hash"] is None


def test_verify_payment_missing_header():
    from app.services.x402 import verify_payment

    result = verify_payment(None, 1.0)
    assert result["valid"] is False
    assert result["tx_hash"] is None
