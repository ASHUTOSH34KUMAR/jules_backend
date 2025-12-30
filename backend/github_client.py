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
    
    async def get_file(self, owner: str, repo: str, path: str, ref: str | None = None):
        """Fetch file content from a repo. Returns decoded text (if base64 encoded)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        if ref:
            url += f"?ref={ref}"
        resp = await self._request("GET", url)
        data = resp.json()
        # Content is base64-encoded for blobs via this endpoint
        if isinstance(data, dict) and data.get("encoding") == "base64" and data.get("content"):
            import base64
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        # Otherwise, return raw content if present
        return data.get("content") or ""

    async def _request(self, method: str, url: str, **kwargs):
        """Internal helper that uses either the provided client or a temporary one."""
        if self.client:
            resp = await self.client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient(headers=self.headers) as client:
                resp = await client.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    async def compare_commits(self, owner: str, repo: str, base: str, head: str):
        """Compare two refs using GitHub's compare API.

        Returns the parsed JSON response. Caller can inspect `ahead_by` and `status`.
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/compare/{base}...{head}"
        try:
            resp = await self._request("GET", url)
            return resp.json()
        except httpx.HTTPStatusError as e:
            resp = e.response
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            raise RuntimeError(f"GitHub API error comparing commits: {resp.status_code} - {err}") from e

    async def create_pull_request(self, owner: str, repo: str, head: str, base: str, title: str, body: str = ""):
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        payload = {"title": title, "head": head, "base": base, "body": body}
        try:
            resp = await self._request("POST", url, json=payload)
            return resp.json()
        except httpx.HTTPStatusError as e:
            # Surface GitHub's error message for easier debugging
            resp = e.response
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            raise RuntimeError(f"GitHub API error creating PR: {resp.status_code} - {err}") from e