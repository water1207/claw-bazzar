"""Tests for the escrow service layer (Solana chain calls mocked)."""

from unittest.mock import patch, MagicMock
from app.services.escrow import (
    check_usdc_balance,
    create_challenge_onchain,
    join_challenge_onchain,
    resolve_challenge_onchain,
    void_challenge_onchain,
)


def test_check_usdc_balance():
    """Should return float USDC balance from Solana RPC."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.value.ui_amount = 5.0
    mock_client.get_token_account_balance.return_value = mock_resp

    with patch("app.services.escrow.get_client", return_value=mock_client):
        balance = check_usdc_balance("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
    assert balance == 5.0


def test_check_usdc_balance_no_account():
    """Should return 0 when token account doesn't exist."""
    mock_client = MagicMock()
    mock_client.get_token_account_balance.side_effect = Exception("Account not found")

    with patch("app.services.escrow.get_client", return_value=mock_client):
        balance = check_usdc_balance("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
    assert balance == 0.0


def test_create_challenge_onchain():
    """Should build and send create_challenge instruction."""
    from solders.pubkey import Pubkey

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.value = "5VERv8NMvzbJMEkV8xnrLkEaWRtSz9CosKDYjCJjBRnbJLgp"
    mock_client.send_raw_transaction.return_value = mock_resp

    mock_keypair = MagicMock()
    dummy_pubkey = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
    mock_keypair.pubkey.return_value = dummy_pubkey

    mock_ix = MagicMock()
    mock_msg = MagicMock()
    mock_tx = MagicMock()
    mock_tx.__bytes__ = MagicMock(return_value=b"fake-tx-bytes")

    with (
        patch("app.services.escrow.get_client", return_value=mock_client),
        patch("app.services.escrow.get_platform_keypair", return_value=mock_keypair),
        patch("app.services.escrow.find_pda", return_value=(dummy_pubkey, 255)),
        patch(
            "app.services.escrow.get_associated_token_address",
            return_value=dummy_pubkey,
        ),
        patch("app.services.escrow.build_instruction", return_value=mock_ix),
        patch("app.services.escrow.Message") as MockMessage,
        patch("app.services.escrow.Transaction") as MockTransaction,
    ):
        MockMessage.new_with_blockhash.return_value = mock_msg
        MockTransaction.new_unsigned.return_value = mock_tx
        tx = create_challenge_onchain(
            "task-1", "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", 8.0, 1.0
        )
    assert tx == "5VERv8NMvzbJMEkV8xnrLkEaWRtSz9CosKDYjCJjBRnbJLgp"


def test_join_challenge_onchain():
    """Should submit pre-signed transaction."""
    import base64

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.value = "3xJoin..."
    mock_client.send_raw_transaction.return_value = mock_resp

    fake_tx = base64.b64encode(b"fake-signed-tx").decode()

    with patch("app.services.escrow.get_client", return_value=mock_client):
        tx = join_challenge_onchain("task-1", fake_tx)
    assert tx == "3xJoin..."
    mock_client.send_raw_transaction.assert_called_once()


def test_resolve_challenge_onchain():
    """Should build resolve_challenge instruction with remaining accounts."""
    from solders.pubkey import Pubkey

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.value = "5xResolve..."
    mock_client.send_raw_transaction.return_value = mock_resp

    mock_keypair = MagicMock()
    dummy_pubkey = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
    mock_keypair.pubkey.return_value = dummy_pubkey

    mock_ix = MagicMock()
    mock_msg = MagicMock()
    mock_tx = MagicMock()
    mock_tx.__bytes__ = MagicMock(return_value=b"fake-tx-bytes")

    with (
        patch("app.services.escrow.get_client", return_value=mock_client),
        patch("app.services.escrow.get_platform_keypair", return_value=mock_keypair),
        patch("app.services.escrow.find_pda", return_value=(dummy_pubkey, 255)),
        patch(
            "app.services.escrow.get_associated_token_address",
            return_value=dummy_pubkey,
        ),
        patch("app.services.escrow.build_instruction", return_value=mock_ix),
        patch("app.services.escrow.Message") as MockMessage,
        patch("app.services.escrow.Transaction") as MockTransaction,
    ):
        MockMessage.new_with_blockhash.return_value = mock_msg
        MockTransaction.new_unsigned.return_value = mock_tx
        tx = resolve_challenge_onchain(
            "task-1",
            "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
            8.0,
            [
                {
                    "challenger": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
                    "refund": True,
                }
            ],
            ["4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"],
            0.3,
        )
    assert tx == "5xResolve..."


def test_void_challenge_onchain():
    """Should build void_challenge instruction."""
    from solders.pubkey import Pubkey

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.value = "5xVoid..."
    mock_client.send_raw_transaction.return_value = mock_resp

    mock_keypair = MagicMock()
    dummy_pubkey = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
    mock_keypair.pubkey.return_value = dummy_pubkey

    mock_ix = MagicMock()
    mock_msg = MagicMock()
    mock_tx = MagicMock()
    mock_tx.__bytes__ = MagicMock(return_value=b"fake-tx-bytes")

    with (
        patch("app.services.escrow.get_client", return_value=mock_client),
        patch("app.services.escrow.get_platform_keypair", return_value=mock_keypair),
        patch("app.services.escrow.find_pda", return_value=(dummy_pubkey, 255)),
        patch(
            "app.services.escrow.get_associated_token_address",
            return_value=dummy_pubkey,
        ),
        patch("app.services.escrow.build_instruction", return_value=mock_ix),
        patch("app.services.escrow.Message") as MockMessage,
        patch("app.services.escrow.Transaction") as MockTransaction,
    ):
        MockMessage.new_with_blockhash.return_value = mock_msg
        MockTransaction.new_unsigned.return_value = mock_tx
        tx = void_challenge_onchain(
            "task-1",
            "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
            9.0,
            [
                {
                    "challenger": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
                    "refund": False,
                }
            ],
            [],
            0.0,
        )
    assert tx == "5xVoid..."
