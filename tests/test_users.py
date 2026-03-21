def test_register_user(client):
    resp = client.post(
        "/users",
        json={
            "nickname": "alice",
            "wallet": "So11111111111111111111111111111111111111112",
            "role": "publisher",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["nickname"] == "alice"
    assert data["wallet"] == "So11111111111111111111111111111111111111112"
    assert data["role"] == "publisher"
    assert data["id"] is not None
    assert data["created_at"] is not None


def test_register_duplicate_nickname(client):
    client.post(
        "/users",
        json={
            "nickname": "bob",
            "wallet": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "role": "worker",
        },
    )
    resp = client.post(
        "/users",
        json={
            "nickname": "bob",
            "wallet": "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe8bv",
            "role": "publisher",
        },
    )
    assert resp.status_code == 400
    assert "nickname" in resp.json()["detail"].lower()


def test_get_user(client):
    create_resp = client.post(
        "/users",
        json={
            "nickname": "charlie",
            "wallet": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "role": "both",
        },
    )
    user_id = create_resp.json()["id"]
    resp = client.get(f"/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["nickname"] == "charlie"
    assert resp.json()["role"] == "both"


def test_get_user_not_found(client):
    resp = client.get("/users/nonexistent-id")
    assert resp.status_code == 404
