def test_register_user(client):
    resp = client.post("/users", json={
        "nickname": "alice",
        "wallet": "0xabc123",
        "role": "publisher",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["nickname"] == "alice"
    assert data["wallet"] == "0xabc123"
    assert data["role"] == "publisher"
    assert data["id"] is not None
    assert data["created_at"] is not None


def test_register_duplicate_nickname(client):
    client.post("/users", json={
        "nickname": "bob",
        "wallet": "0x111",
        "role": "worker",
    })
    resp = client.post("/users", json={
        "nickname": "bob",
        "wallet": "0x222",
        "role": "publisher",
    })
    assert resp.status_code == 400
    assert "nickname" in resp.json()["detail"].lower()


def test_get_user(client):
    create_resp = client.post("/users", json={
        "nickname": "charlie",
        "wallet": "0xdef456",
        "role": "both",
    })
    user_id = create_resp.json()["id"]
    resp = client.get(f"/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["nickname"] == "charlie"
    assert resp.json()["role"] == "both"


def test_get_user_not_found(client):
    resp = client.get("/users/nonexistent-id")
    assert resp.status_code == 404
