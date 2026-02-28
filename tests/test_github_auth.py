"""Tests for GitHub OAuth binding flow (/auth/github*)."""

from unittest.mock import patch, MagicMock

from app.models import User, UserRole


def _create_user(db, user_id="user1", wallet="0xabc", nickname="tester"):
    user = User(id=user_id, wallet=wallet, nickname=nickname, role=UserRole.worker)
    db.add(user)
    db.commit()
    return user


# ---------- GET /auth/github ----------

def test_github_login_redirect(client_with_db):
    client, db = client_with_db
    _create_user(db)
    with patch("app.routers.auth.GITHUB_CLIENT_ID", "test_client_id"):
        resp = client.get("/auth/github?user_id=user1", follow_redirects=False)
    assert resp.status_code == 307
    assert "github.com/login/oauth/authorize" in resp.headers["location"]
    assert "client_id=test_client_id" in resp.headers["location"]
    assert "state=user1" in resp.headers["location"]


def test_github_login_not_configured(client_with_db):
    client, db = client_with_db
    _create_user(db)
    with patch("app.routers.auth.GITHUB_CLIENT_ID", ""):
        resp = client.get("/auth/github?user_id=user1")
    assert resp.status_code == 500


# ---------- GET /auth/github/callback ----------

def _mock_github_oauth(github_user_id="12345"):
    """Return patches for GitHub token exchange and user info API."""
    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "gho_fake_token"}

    user_resp = MagicMock()
    user_resp.json.return_value = {"id": github_user_id, "login": "testuser"}

    def side_effect(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        if "access_token" in url:
            return token_resp
        return MagicMock()

    return token_resp, user_resp


def test_github_callback_success(client_with_db):
    """Successful GitHub binding: sets github_id, applies trust bonus."""
    client, db = client_with_db
    _create_user(db)

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "gho_fake"}
    user_resp = MagicMock()
    user_resp.json.return_value = {"id": 12345, "login": "testuser"}

    with patch("app.routers.auth.GITHUB_CLIENT_ID", "cid"), \
         patch("app.routers.auth.GITHUB_CLIENT_SECRET", "csec"), \
         patch("app.routers.auth.httpx.post", return_value=token_resp), \
         patch("app.routers.auth.httpx.get", return_value=user_resp):
        resp = client.get(
            "/auth/github/callback?code=testcode&state=user1",
            follow_redirects=False,
        )

    assert resp.status_code == 307
    assert "github_bound=true" in resp.headers["location"]

    db.expire_all()
    user = db.query(User).filter_by(id="user1").first()
    assert user.github_id == "12345"
    assert user.github_bonus_claimed is True
    # trust_score should have increased by 50 (github_bind event)
    assert user.trust_score == 550


def test_github_callback_user_not_found(client_with_db):
    client, db = client_with_db
    # No user created

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "gho_fake"}

    with patch("app.routers.auth.GITHUB_CLIENT_ID", "cid"), \
         patch("app.routers.auth.GITHUB_CLIENT_SECRET", "csec"), \
         patch("app.routers.auth.httpx.post", return_value=token_resp):
        resp = client.get("/auth/github/callback?code=testcode&state=nouser")

    assert resp.status_code == 404


def test_github_callback_already_bound(client_with_db):
    """Cannot bind GitHub twice."""
    client, db = client_with_db
    user = _create_user(db)
    user.github_id = "99999"
    user.github_bonus_claimed = True
    db.commit()

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "gho_fake"}

    with patch("app.routers.auth.GITHUB_CLIENT_ID", "cid"), \
         patch("app.routers.auth.GITHUB_CLIENT_SECRET", "csec"), \
         patch("app.routers.auth.httpx.post", return_value=token_resp):
        resp = client.get("/auth/github/callback?code=testcode&state=user1")

    assert resp.status_code == 400
    assert "already bound" in resp.json()["detail"].lower()


def test_github_callback_token_exchange_fails(client_with_db):
    """GitHub returns no access_token."""
    client, db = client_with_db
    _create_user(db)

    token_resp = MagicMock()
    token_resp.json.return_value = {"error": "bad_verification_code"}

    with patch("app.routers.auth.GITHUB_CLIENT_ID", "cid"), \
         patch("app.routers.auth.GITHUB_CLIENT_SECRET", "csec"), \
         patch("app.routers.auth.httpx.post", return_value=token_resp):
        resp = client.get("/auth/github/callback?code=badcode&state=user1")

    assert resp.status_code == 400
    assert "token" in resp.json()["detail"].lower()


def test_github_callback_duplicate_github_account(client_with_db):
    """Same GitHub account cannot bind to two different users."""
    client, db = client_with_db
    # User A already bound to github_id=12345
    user_a = User(id="userA", wallet="0xaaa", nickname="A", role=UserRole.worker,
                  github_id="12345", github_bonus_claimed=True)
    db.add(user_a)
    # User B tries to bind same GitHub
    user_b = User(id="userB", wallet="0xbbb", nickname="B", role=UserRole.worker)
    db.add(user_b)
    db.commit()

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "gho_fake"}
    user_resp = MagicMock()
    user_resp.json.return_value = {"id": 12345, "login": "testuser"}

    with patch("app.routers.auth.GITHUB_CLIENT_ID", "cid"), \
         patch("app.routers.auth.GITHUB_CLIENT_SECRET", "csec"), \
         patch("app.routers.auth.httpx.post", return_value=token_resp), \
         patch("app.routers.auth.httpx.get", return_value=user_resp):
        resp = client.get("/auth/github/callback?code=testcode&state=userB")

    assert resp.status_code == 400
    assert "another user" in resp.json()["detail"].lower()


def test_github_callback_empty_github_id(client_with_db):
    """GitHub API returns no user ID."""
    client, db = client_with_db
    _create_user(db)

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "gho_fake"}
    user_resp = MagicMock()
    user_resp.json.return_value = {"login": "testuser"}  # no "id" field

    with patch("app.routers.auth.GITHUB_CLIENT_ID", "cid"), \
         patch("app.routers.auth.GITHUB_CLIENT_SECRET", "csec"), \
         patch("app.routers.auth.httpx.post", return_value=token_resp), \
         patch("app.routers.auth.httpx.get", return_value=user_resp):
        resp = client.get("/auth/github/callback?code=testcode&state=user1")

    assert resp.status_code == 400
    assert "github user" in resp.json()["detail"].lower()
