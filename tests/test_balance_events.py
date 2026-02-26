from unittest.mock import patch


PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                     return_value={"valid": True, "tx_hash": "0xtest123"})
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def test_balance_events_empty(client):
    """New user with no activity has empty balance events."""
    resp = client.post("/users", json={"nickname": "be-empty", "wallet": "0xBE0", "role": "worker"})
    user_id = resp.json()["id"]

    resp = client.get(f"/users/{user_id}/balance-events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_balance_events_user_not_found(client):
    resp = client.get("/users/nonexistent-id/balance-events")
    assert resp.status_code == 404


def test_balance_events_publisher_bounty(client):
    """Publisher who created a paid task sees bounty_paid event."""
    pub = client.post("/users", json={"nickname": "be-pub", "wallet": "0xBEP", "role": "publisher"})
    pub_id = pub.json()["id"]

    with PAYMENT_MOCK:
        task = client.post("/tasks", json={
            "title": "BE Test Task",
            "description": "test",
            "type": "fastest_first",
            "threshold": 0.8,
            "deadline": "2099-01-01T00:00:00Z",
            "publisher_id": pub_id,
            "bounty": 5.0,
        }, headers=PAYMENT_HEADERS)
    assert task.status_code == 201

    resp = client.get(f"/users/{pub_id}/balance-events")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    evt = data[0]
    assert evt["event_type"] == "bounty_paid"
    assert evt["role"] == "publisher"
    assert evt["direction"] == "outflow"
    assert evt["amount"] == 5.0
    assert evt["task_title"] == "BE Test Task"
    assert evt["tx_hash"] == "0xtest123"


def test_balance_events_worker_payout(client):
    """Worker who won a task sees payout_received event."""
    pub = client.post("/users", json={"nickname": "be-pub2", "wallet": "0xBEP2", "role": "publisher"})
    pub_id = pub.json()["id"]
    wrk = client.post("/users", json={"nickname": "be-wrk", "wallet": "0xBEW", "role": "worker"})
    wrk_id = wrk.json()["id"]

    with PAYMENT_MOCK:
        task_resp = client.post("/tasks", json={
            "title": "Payout Test",
            "description": "test",
            "type": "fastest_first",
            "threshold": 0.5,
            "deadline": "2099-01-01T00:00:00Z",
            "publisher_id": pub_id,
            "bounty": 10.0,
        }, headers=PAYMENT_HEADERS)
    task_id = task_resp.json()["id"]

    # Submit
    sub_resp = client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": wrk_id, "content": "answer",
    })
    sub_id = sub_resp.json()["id"]

    # Score above threshold → triggers payout
    with patch("app.services.payout._send_usdc_transfer", return_value="0xpayout123"):
        client.post(f"/internal/submissions/{sub_id}/score",
                    json={"score": 0.9, "feedback": "ok"})

    resp = client.get(f"/users/{wrk_id}/balance-events")
    data = resp.json()
    payout_events = [e for e in data if e["event_type"] == "payout_received"]
    assert len(payout_events) == 1
    evt = payout_events[0]
    assert evt["role"] == "worker"
    assert evt["direction"] == "inflow"
    assert evt["amount"] > 0
    assert evt["task_title"] == "Payout Test"
    assert evt["tx_hash"] == "0xpayout123"


def test_balance_events_worker_deposit(client):
    """Worker who submitted to quality_first task sees deposit_paid event."""
    pub = client.post("/users", json={"nickname": "be-pub3", "wallet": "0xBEP3", "role": "publisher"})
    pub_id = pub.json()["id"]
    wrk = client.post("/users", json={"nickname": "be-wrk2", "wallet": "0xBEW2", "role": "worker"})
    wrk_id = wrk.json()["id"]

    with PAYMENT_MOCK:
        task_resp = client.post("/tasks", json={
            "title": "Deposit Test",
            "description": "test",
            "type": "quality_first",
            "threshold": 0.8,
            "deadline": "2099-01-01T00:00:00Z",
            "publisher_id": pub_id,
            "bounty": 10.0,
        }, headers=PAYMENT_HEADERS)
    task_id = task_resp.json()["id"]

    client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": wrk_id, "content": "my work",
    })

    resp = client.get(f"/users/{wrk_id}/balance-events")
    data = resp.json()
    deposit_events = [e for e in data if e["event_type"] == "deposit_paid"]
    assert len(deposit_events) == 1
    assert deposit_events[0]["direction"] == "outflow"
    assert deposit_events[0]["amount"] == 1.0  # default 10% of bounty
