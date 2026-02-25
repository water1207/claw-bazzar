from unittest.mock import patch, MagicMock
from app.models import User, UserRole, TrustTier


def test_get_trust_profile(client):
    resp = client.post("/users", json={
        "nickname": "trust-user", "wallet": "0xTRUST", "role": "worker"
    })
    user_id = resp.json()["id"]

    resp = client.get(f"/users/{user_id}/trust")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trust_score"] == 500.0
    assert data["trust_tier"] == "A"
    assert data["challenge_deposit_rate"] == 0.10
    assert data["platform_fee_rate"] == 0.20
    assert data["can_accept_tasks"] is True
    assert data["can_challenge"] is True


def test_trust_quote(client):
    resp = client.post("/users", json={
        "nickname": "quote-user", "wallet": "0xQUOTE", "role": "worker"
    })
    user_id = resp.json()["id"]

    resp = client.get(f"/trust/quote?user_id={user_id}&bounty=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trust_tier"] == "A"
    assert data["challenge_deposit_rate"] == 0.10
    assert data["challenge_deposit_amount"] == 10.0
    assert data["service_fee"] == 0.01


def test_get_trust_events(client):
    resp = client.post("/users", json={
        "nickname": "events-user", "wallet": "0xEVT", "role": "worker"
    })
    user_id = resp.json()["id"]

    resp = client.get(f"/users/{user_id}/trust/events")
    assert resp.status_code == 200
    assert resp.json() == []
