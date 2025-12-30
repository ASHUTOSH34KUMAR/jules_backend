# backend/main.py
from fastapi import FastAPI
from backend.api.auth_github import router as github_auth_router
from backend.api.github_routes import router as github_routes_router
from backend.core.db import Base, engine
from backend.api.tasks import router as tasks_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path

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

    # Ensure new columns are added when model changes (simple auto-migration for dev)
    # For example, older DBs may lack the `plan_text` column — add it if missing
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("tasks")] if inspector.has_table("tasks") else []
    if "plan_text" not in cols:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN plan_text TEXT DEFAULT ''"))
        except Exception:
            # If adding column fails for any reason, don't prevent the app from starting.
            pass

    if "plan_generated_by" not in cols:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN plan_generated_by VARCHAR(255)"))
        except Exception:
            pass

@app.get("/health")
async def health():
    return {"status": "ok"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def ui():
    return Path("backend/ui/index.html").read_text(encoding="utf-8")