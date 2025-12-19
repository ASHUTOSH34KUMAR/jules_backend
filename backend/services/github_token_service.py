# backend/services/github_token_service.py
from backend.core.db import SessionLocal
from backend.models import GitHubToken

def get_token_for_user(user_id: int) -> str | None:
    db = SessionLocal()
    try:
        token_obj = db.query(GitHubToken).filter(GitHubToken.user_id == user_id).first()
        return token_obj.access_token if token_obj else None
    finally:
        db.close()
