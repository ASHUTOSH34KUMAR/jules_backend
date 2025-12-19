# backend/github_client.py
import httpx

class GitHubClient:
    def __init__(self, access_token: str):
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
