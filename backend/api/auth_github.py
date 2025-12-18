# backend/api/auth_github.py
import secrets
import urllib.parse
from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse
from backend.core.config import settings

router = APIRouter(prefix="/auth/github", tags=["auth"])

# For now, we'll keep state in memory (for dev only)
STATE_TOKENS = set()

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
        user_data = user_resp.json()

    # ⚠️ DEV ONLY: just return token + user info so we see it works
    return {
        "access_token": access_token,
        "github_user": {
            "id": user_data.get("id"),
            "login": user_data.get("login"),
            "name": user_data.get("name"),
        },
    }

