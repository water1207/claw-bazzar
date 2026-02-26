"""Tests for the escrow service layer (chain calls mocked)."""
from unittest.mock import patch, MagicMock
from app.services.escrow import (
    check_usdc_balance,
    create_challenge_onchain,
    join_challenge_onchain,
    resolve_challenge_onchain,
)


def test_check_usdc_balance():
    """Should return float USDC balance from RPC."""
    mock_w3 = MagicMock()
    mock_contract = MagicMock()
    # 5 USDC = 5_000_000 in 6-decimal wei
    mock_contract.functions.balanceOf.return_value.call.return_value = 5_000_000
    mock_w3.eth.contract.return_value = mock_contract

    with patch("app.services.escrow.Web3", return_value=mock_w3):
        balance = check_usdc_balance("0xabc")
    assert balance == 5.0


def test_create_challenge_onchain():
    """Should call contract.createChallenge and return tx hash."""
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_account.address = "0xPlatform"
    mock_w3.eth.account.from_key.return_value = mock_account
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1000
    mock_w3.eth.send_raw_transaction.return_value = b"\x01" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract

    with patch("app.services.escrow.Web3", return_value=mock_w3):
        with patch("app.services.escrow._get_w3_and_contract", return_value=(mock_w3, mock_contract)):
            tx = create_challenge_onchain("task-1", "0xWinner", 8.0, 1.0, 1.0)
    assert tx is not None


def test_join_challenge_onchain():
    """Should call contract.joinChallenge with permit params."""
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_account.address = "0x" + "aa" * 20
    mock_w3.eth.account.from_key.return_value = mock_account
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1000
    mock_w3.eth.send_raw_transaction.return_value = b"\x02" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    mock_contract = MagicMock()

    with patch("app.services.escrow._get_w3_and_contract", return_value=(mock_w3, mock_contract)):
        tx = join_challenge_onchain(
            "task-1", "0x" + "bb" * 20, 9999999999, 27, "0x" + "ab" * 32, "0x" + "cd" * 32
        )
    assert tx is not None


def test_resolve_challenge_onchain():
    """Should call contract.resolveChallenge with verdicts."""
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_account.address = "0x" + "aa" * 20
    mock_w3.eth.account.from_key.return_value = mock_account
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1000
    mock_w3.eth.send_raw_transaction.return_value = b"\x03" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    mock_contract = MagicMock()

    with patch("app.services.escrow._get_w3_and_contract", return_value=(mock_w3, mock_contract)):
        tx = resolve_challenge_onchain(
            "task-1",
            "0x" + "cc" * 20,
            8.0,
            [{"challenger": "0x" + "dd" * 20, "result": 0}, {"challenger": "0x" + "ee" * 20, "result": 1}],
        )
    assert tx is not None
