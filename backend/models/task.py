# backend/models/task.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from backend.core.db import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # e.g. "owner/repo"
    repo_full_name = Column(String, nullable=False)          # "owner/repo"
    branch = Column(String, nullable=False)                  # "main", "dev", etc.
    base_commit_sha = Column(String, nullable=True)          # commit hash at task creation

    prompt = Column(String, nullable=False)                  # what user asked: "Upgrade Next.js..."
    target_file = Column(String, nullable=True)               # optional: "package.json", "app/page.tsx", etc.
    diff_text = Column(Text, nullable=True, default="")                     # generated diff text


    work_branch = Column(String, nullable=True)        # git branch created for this task
    pr_url = Column(String, nullable=True)               # URL of created PR, if any
    pr_number = Column(Integer, nullable=True)            # PR number, if any

    status = Column(String, nullable=False, default="QUEUED")  # QUEUED, RUNNING, COMPLETED, FAILED

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    log_text = Column(Text, nullable=True, default="")                     # logs or error messages
