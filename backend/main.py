# backend/main.py
from fastapi import FastAPI
from backend.api.auth_github import router as github_auth_router

app = FastAPI(title="Jules Backend")

app.include_router(github_auth_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
