# backend/github_client.py
import httpx
from typing import Union

class GitHubClient:
    def __init__(self, client_or_token: Union[httpx.AsyncClient, str]):
        # Standard base URL for GitHub API
        self.base_url = "https://api.github.com"

        # If caller passed an AsyncClient, reuse it (e.g., publish_task does this).
        if isinstance(client_or_token, httpx.AsyncClient):
            self.client = client_or_token
            self.headers = getattr(self.client, "headers", None)
        else:
            # If caller passed a token string, build headers and use ad-hoc clients.
            self.client = None
            access_token = str(client_or_token)
            self.headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            }

    async def get_repos(self):
        async with httpx.AsyncClient(headers=self.headers) as client:
            resp = await client.get("https://api.github.com/user/repos?per_page=100")
            resp.raise_for_status()
            return resp.json()

    async def get_branches(self, owner: str, repo: str):
        url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
        async with httpx.AsyncClient(headers=self.headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def get_branch(self, owner: str, repo: str, branch: str):
        # gets one branch with commit SHA
        url = f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}"
        async with httpx.AsyncClient(headers=self.headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    

    async def _request(self, method: str, url: str, **kwargs):
        """Internal helper that uses either the provided client or a temporary one."""
        if self.client:
            resp = await self.client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient(headers=self.headers) as client:
                resp = await client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    async def create_pull_request(self, owner: str, repo: str, head: str, base: str, title: str, body: str = ""):
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        payload = {"title": title, "head": head, "base": base, "body": body}
        resp = await self._request("POST", url, json=payload)
        return resp.json()