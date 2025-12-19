# backend/api/github_routes.py
from fastapi import APIRouter, HTTPException
from backend.github_client import GitHubClient
from backend.services.github_token_service import get_token_for_user

router = APIRouter(prefix="/github", tags=["github"])

@router.get("/repos")
async def list_repos():
    user_id = 1  # TODO: replace with real session user later

    token = get_token_for_user(user_id)
    if not token:
        raise HTTPException(status_code=400, detail="No GitHub token found for user")

    client = GitHubClient(token)
    repos = await client.get_repos()

    # Simplify response
    simplified = [
        {
            "full_name": r["full_name"],
            "private": r["private"],
            "default_branch": r["default_branch"],
        }
        for r in repos
    ]

    return simplified


@router.get("/repos/{owner}/{repo}/branches")
async def list_branches(owner: str, repo: str):
    user_id = 1  # TODO: real session user later

    token = get_token_for_user(user_id)
    if not token:
        raise HTTPException(status_code=400, detail="No GitHub token found for user")

    client = GitHubClient(token)
    branches = await client.get_branches(owner, repo)

    return [b["name"] for b in branches]
