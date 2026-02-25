import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.services.trust import apply_event, TrustEventType

router = APIRouter(prefix="/auth")

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI",
                                      "http://localhost:8000/auth/github/callback")


@router.get("/github")
def github_login(user_id: str = Query(...)):
    if not GITHUB_CLIENT_ID:
        raise HTTPException(500, "GitHub OAuth not configured")
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=read:user"
        f"&state={user_id}"
    )
    return RedirectResponse(url)


@router.get("/github/callback")
def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    user_id = state
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.github_bonus_claimed:
        raise HTTPException(400, "GitHub already bound")

    resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        json={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
        },
        headers={"Accept": "application/json"},
    )
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, "Failed to get GitHub token")

    gh_resp = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    gh_user = gh_resp.json()
    github_id = str(gh_user.get("id", ""))
    if not github_id:
        raise HTTPException(400, "Failed to get GitHub user")

    existing = db.query(User).filter_by(github_id=github_id).first()
    if existing and existing.id != user_id:
        raise HTTPException(400, "GitHub account already bound to another user")

    user.github_id = github_id
    user.github_bonus_claimed = True
    apply_event(db, user_id, TrustEventType.github_bind)

    return RedirectResponse(f"http://localhost:3000/tasks?github_bound=true")
