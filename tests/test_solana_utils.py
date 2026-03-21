import hashlib
from app.services.solana_utils import (
    task_id_to_seed,
    build_anchor_discriminator,
    usdc_to_lamports,
    lamports_to_usdc,
)


def test_task_id_to_seed():
    seed = task_id_to_seed("test-uuid-123")
    assert len(seed) == 32
    assert seed == hashlib.sha256(b"test-uuid-123").digest()


def test_build_anchor_discriminator():
    disc = build_anchor_discriminator("create_challenge")
    assert len(disc) == 8
    expected = hashlib.sha256(b"global:create_challenge").digest()[:8]
    assert disc == expected


def test_usdc_to_lamports():
    assert usdc_to_lamports(1.0) == 1_000_000
    assert usdc_to_lamports(0.01) == 10_000
    assert usdc_to_lamports(100.5) == 100_500_000


def test_lamports_to_usdc():
    assert lamports_to_usdc(1_000_000) == 1.0
    assert lamports_to_usdc(10_000) == 0.01
