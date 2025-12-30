# backend/api/auth_github.py
import httpx
import secrets
import urllib.parse

from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse

from backend.core.config import settings
from backend.core.db import SessionLocal
from backend.models import User, GitHubToken

router = APIRouter(prefix="/auth/github", tags=["auth"])

# For now, we'll keep state in memory (for dev only)
STATE_TOKENS = set()

def get_or_create_user_from_github(db, github_user_data: dict) -> User:
    github_id = github_user_data.get("id")
    github_login = github_user_data.get("login")
    name = github_user_data.get("name")

    user = db.query(User).filter(User.github_id == github_id).first()
    if user:
        # Optionally update name/login
        user.github_login = github_login
        user.name = name
    else:
        user = User(
            github_id=github_id,
            github_login=github_login,
            name=name,
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    return user


def store_github_token(db, user: User, access_token: str, token_type: str | None, scope: str | None):
    # For simplicity, we keep only one token per user.
    existing = db.query(GitHubToken).filter(GitHubToken.user_id == user.id).first()
    if existing:
        existing.access_token = access_token
        existing.token_type = token_type
        existing.scope = scope
    else:
        token = GitHubToken(
            user_id=user.id,
            access_token=access_token,
            token_type=token_type,
            scope=scope,
        )
        db.add(token)

    db.commit()


@router.get("/login")
def github_login():
    # 1. Generate random state token (protects against CSRF)
    state = secrets.token_urlsafe(16)
    STATE_TOKENS.add(state)

    # 2. Build GitHub authorization URL
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_CALLBACK_URL,
        "scope": settings.GITHUB_OAUTH_SCOPES,
        "state": state,
        "allow_signup": "true",
    }
    url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)

    # 3. Redirect the user to GitHub OAuth
    return RedirectResponse(url)


@router.get("/callback")
async def github_callback(request: Request, code: str = None, state: str = None):
    # 1. Validate state
    if not state or state not in STATE_TOKENS:
        raise HTTPException(status_code=400, detail="Invalid state")
    STATE_TOKENS.discard(state)

    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    # 2. Exchange code for access_token
    token_url = "https://github.com/login/oauth/access_token"
    data = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.GITHUB_OAUTH_CALLBACK_URL,
        "state": state,
    }

    async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
        token_resp = await client.post(token_url, data=data)
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    token_type = token_data.get("token_type")
    scope = token_data.get("scope")

    if not access_token:
        raise HTTPException(status_code=400, detail="Failed to get access token")

    # 3. Use access_token to fetch user info from GitHub API
    async with httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
    ) as client:
        user_resp = await client.get("https://api.github.com/user")
        user_resp.raise_for_status()
        github_user_data = user_resp.json()

    # 4. Store user + token in DB
    db = SessionLocal()
    try:
        user = get_or_create_user_from_github(db, github_user_data)
        store_github_token(db, user, access_token, token_type, scope)
    finally:
        db.close()

    # 5. Return simple message (no token in response now)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="user_id", value=str(user.id), httponly=True, samesite="lax")
    return response
