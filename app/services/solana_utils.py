"""Shared Solana utilities for backend services."""

import hashlib
import json
import os

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID

SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
USDC_MINT = Pubkey.from_string(
    os.environ.get("USDC_MINT", "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
)
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "")
ESCROW_PROGRAM_ID = os.environ.get("ESCROW_PROGRAM_ID", "")
STAKING_PROGRAM_ID = os.environ.get("STAKING_PROGRAM_ID", "")


def get_client() -> Client:
    return Client(SOLANA_RPC_URL)


def get_platform_keypair() -> Keypair:
    raw = os.environ.get("PLATFORM_PRIVATE_KEY", "[]")
    secret = bytes(json.loads(raw))
    return Keypair.from_bytes(secret)


def task_id_to_seed(task_id: str) -> bytes:
    """Convert task UUID to 32-byte seed via SHA-256."""
    return hashlib.sha256(task_id.encode()).digest()


def build_anchor_discriminator(method_name: str) -> bytes:
    """Compute Anchor 8-byte instruction discriminator."""
    return hashlib.sha256(f"global:{method_name}".encode()).digest()[:8]


def usdc_to_lamports(amount: float) -> int:
    """Convert USDC amount to smallest unit (6 decimals)."""
    return int(amount * 10**6)


def lamports_to_usdc(lamports: int) -> float:
    """Convert smallest unit back to USDC."""
    return lamports / 10**6


def find_pda(seeds: list[bytes], program_id: Pubkey) -> tuple[Pubkey, int]:
    """Find PDA for given seeds and program."""
    return Pubkey.find_program_address(seeds, program_id)


def get_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive Associated Token Account address."""
    ata, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return ata


def build_instruction(
    program_id: Pubkey,
    method_name: str,
    args_data: bytes,
    accounts: list[AccountMeta],
) -> Instruction:
    """Build an Anchor instruction with discriminator + serialized args."""
    discriminator = build_anchor_discriminator(method_name)
    data = discriminator + args_data
    return Instruction(program_id, data, accounts)
