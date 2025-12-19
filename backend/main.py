# backend/main.py
from fastapi import FastAPI
from backend.api.auth_github import router as github_auth_router
from backend.api.github_routes import router as github_routes_router
from backend.core.db import Base, engine
from backend.api.tasks import router as tasks_router

import backend.models

app = FastAPI(title="Jules Backend")

# Include routers
app.include_router(github_auth_router)
app.include_router(github_routes_router)
app.include_router(tasks_router)

@app.on_event("startup")
def on_startup():
    # Create DB tables (for now, simple auto-create)
    Base.metadata.create_all(bind=engine)

@app.get("/health")
async def health():
    return {"status": "ok"}
