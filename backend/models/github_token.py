# backend/models/github_token.py
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from backend.core.db import Base

class GitHubToken(Base):
    __tablename__ = "github_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    access_token = Column(String, nullable=False)
    token_type = Column(String, nullable=True)        # e.g. "bearer"
    scope = Column(String, nullable=True)             # e.g. "repo,read:user"

    # Optional: relationship back to User (we can use later if needed)
    user = relationship("User", backref="github_tokens")
