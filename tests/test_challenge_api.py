from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.models import TaskStatus

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def make_quality_task(client, bounty=10.0):
    body = {
        "title": "Q", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future(),
        "publisher_id": "pub", "bounty": bounty,
        "challenge_duration": 7200,
        "acceptance_criteria": ["验收标准"],
    }
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def submit(client, task_id, worker_id, content="answer"):
    with patch("app.routers.submissions.invoke_oracle"):
        return client.post(
            f"/tasks/{task_id}/submissions",
            json={"worker_id": worker_id, "content": content},
        ).json()


def setup_challenge_window(client, task_id, winner_sub_id):
    """Manually set task to challenge_window state via direct DB manipulation."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    from app.models import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = winner_sub_id
    task.challenge_window_end = datetime.now(timezone.utc) + timedelta(hours=2)
    db.commit()


def test_create_challenge(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1", "winner content")
    s2 = submit(client, task["id"], "w2", "challenger content")

    # Score submissions via internal endpoint
    client.post(f"/internal/submissions/{s1['id']}/score", json={"score": 0.9})
    client.post(f"/internal/submissions/{s2['id']}/score", json={"score": 0.7})

    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "My solution handles edge cases better",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["challenger_submission_id"] == s2["id"]
    assert data["target_submission_id"] == s1["id"]
    assert data["status"] == "pending"
    assert data["verdict"] is None


def test_challenge_rejected_when_not_in_window(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    # Task is still 'open', not 'challenge_window'
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "test",
    })
    assert resp.status_code == 400
    assert "challenge_window" in resp.json()["detail"]


def test_challenge_rejected_winner_cannot_challenge_self(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s1["id"],
        "reason": "challenging myself",
    })
    assert resp.status_code == 400
    assert "winner" in resp.json()["detail"].lower()


def test_challenge_rejected_submission_not_in_task(client):
    task1 = make_quality_task(client)
    task2 = make_quality_task(client)
    s1 = submit(client, task1["id"], "w1")
    s2 = submit(client, task2["id"], "w2")

    setup_challenge_window(client, task1["id"], s1["id"])

    resp = client.post(f"/tasks/{task1['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "wrong task",
    })
    assert resp.status_code == 400
    assert "not belong" in resp.json()["detail"].lower() or "not found" in resp.json()["detail"].lower()


def test_challenge_rejected_duplicate(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "first attempt",
    })
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "second attempt",
    })
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"].lower()


def test_list_challenges(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    s3 = submit(client, task["id"], "w3")

    setup_challenge_window(client, task["id"], s1["id"])

    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"], "reason": "r1"})
    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s3["id"], "reason": "r2"})

    resp = client.get(f"/tasks/{task['id']}/challenges")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_challenge(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    created = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"], "reason": "test"}).json()

    resp = client.get(f"/tasks/{task['id']}/challenges/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_create_challenge_with_wallet_and_permit(client):
    """New escrow fields are accepted and returned."""
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1", "winner")
    s2 = submit(client, task["id"], "w2", "challenger")
    setup_challenge_window(client, task["id"], s1["id"])

    with patch("app.routers.challenges.check_usdc_balance", return_value=100.0), \
         patch("app.routers.challenges.join_challenge_onchain", return_value="0xtx"):
        resp = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "better solution",
            "challenger_wallet": "0x1234567890abcdef1234567890abcdef12345678",
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["challenger_wallet"] == "0x1234567890abcdef1234567890abcdef12345678"


def test_challenge_rejected_insufficient_balance(client):
    """Reject if challenger's USDC balance is too low."""
    task = make_quality_task(client, bounty=10.0)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    setup_challenge_window(client, task["id"], s1["id"])

    with patch("app.routers.challenges.check_usdc_balance", return_value=0.5):
        resp = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "test",
            "challenger_wallet": "0x" + "ab" * 20,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp.status_code == 400
    assert "余额不足" in resp.json()["detail"] or "balance" in resp.json()["detail"].lower()


def test_challenge_rejected_rate_limit(client):
    """Reject if same wallet challenged within 1 minute."""
    task = make_quality_task(client, bounty=10.0)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    s3 = submit(client, task["id"], "w3")
    setup_challenge_window(client, task["id"], s1["id"])

    wallet = "0x" + "ab" * 20

    with patch("app.routers.challenges.check_usdc_balance", return_value=100.0), \
         patch("app.routers.challenges.join_challenge_onchain", return_value="0xtx1"):
        resp1 = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "first",
            "challenger_wallet": wallet,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
        assert resp1.status_code == 201

        # Second challenge from same wallet within 1 minute
        resp2 = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s3["id"],
            "reason": "second",
            "challenger_wallet": wallet,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp2.status_code == 429


def test_challenge_with_escrow_happy_path(client):
    """Full happy path: balance check -> rate limit -> join_challenge_onchain."""
    task = make_quality_task(client, bounty=10.0)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    setup_challenge_window(client, task["id"], s1["id"])

    with patch("app.routers.challenges.check_usdc_balance", return_value=100.0), \
         patch("app.routers.challenges.join_challenge_onchain", return_value="0xescrow_tx"):
        resp = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "my answer is better",
            "challenger_wallet": "0x" + "ab" * 20,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["deposit_tx_hash"] == "0xescrow_tx"
