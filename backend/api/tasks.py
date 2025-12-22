# backend/api/tasks.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.services.orchestrator import start_task_container
from backend.core.db import get_db
from backend.models import Task
from backend.services.github_token_service import get_token_for_user
from backend.github_client import GitHubClient

router = APIRouter(prefix="/tasks", tags=["tasks"])

# ----- Pydantic schemas -----

class TaskCreate(BaseModel):
    repo_full_name: str   # "owner/repo"
    branch: str           # "main"
    prompt: str           # "Upgrade to Next.js 15..."


class TaskLogAppend(BaseModel):
    message: str

class TaskResponse(BaseModel):
    id: int
    repo_full_name: str
    branch: str
    base_commit_sha: str | None
    prompt: str
    status: str

    class Config:
        from_attributes = True  # so we can return ORM model directly


# ----- Routes -----

@router.post("", response_model=TaskResponse)
async def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    # TODO: replace hard-coded user with real auth later
    user_id = 1

    # 1. Get user's GitHub token
    token = get_token_for_user(user_id)
    if not token:
        raise HTTPException(status_code=400, detail="No GitHub token found for user")

    # 2. Parse owner/repo
    if "/" not in payload.repo_full_name:
        raise HTTPException(status_code=400, detail="repo_full_name must be 'owner/repo'")

    owner, repo = payload.repo_full_name.split("/", 1)

    # 3. Validate branch & get base commit SHA from GitHub
    client = GitHubClient(token)
    try:
        branch_data = await client.get_branch(owner, repo, payload.branch)
    except Exception as e:
        # You can log e here
        raise HTTPException(status_code=400, detail="Invalid repo or branch") from e

    base_commit_sha = branch_data["commit"]["sha"]

    # 4. Create Task row in DB
    task = Task(
        user_id=user_id,
        repo_full_name=payload.repo_full_name,
        branch=payload.branch,
        base_commit_sha=base_commit_sha,
        prompt=payload.prompt,
        status="QUEUED",
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return task


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/start", response_model=TaskResponse)
def start_task(task_id: int, db: Session = Depends(get_db)):
    # TODO: real auth later, for now assume user_id=1
    user_id = 1

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("QUEUED", "FAILED"):
        raise HTTPException(status_code=400, detail=f"Cannot start task in status {task.status}")

    # Mark as RUNNING
    task.status = "RUNNING"
    db.commit()
    db.refresh(task)

    # Fire-and-forget: start Docker container
    start_task_container(task)

    return task


@router.post("/{task_id}/logs")
def append_log(task_id: int, payload: TaskLogAppend, db: Session = Depends(get_db)):
    user_id = 1  # TODO real auth later

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.log_text is None:
        task.log_text = ""

    task.log_text += payload.message + "\n"
    db.commit()
    return {"ok": True}

@router.get("/{task_id}/logs")
def get_logs(task_id: int, db: Session = Depends(get_db)):
    user_id = 1

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task_id": task.id, "logs": task.log_text or ""}


@router.post("/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "COMPLETED"
    db.commit()
    return {"ok": True, "status": task.status}


class TaskFail(BaseModel):
    reason: str | None = None

@router.post("/{task_id}/fail")
def fail_task(task_id: int, payload: TaskFail, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "FAILED"
    if payload.reason:
        if task.log_text is None:
            task.log_text = ""
        task.log_text += f"[FAIL] {payload.reason}\n"
    db.commit()
    return {"ok": True, "status": task.status}
