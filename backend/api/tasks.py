# backend/api/tasks.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.models.user import User
from backend.services.orchestrator import start_task_container
from backend.core.db import get_db
from backend.models import Task
from backend.services.github_token_service import get_token_for_user
from backend.github_client import GitHubClient
from pydantic import BaseModel
import httpx
from backend.models.github_token import GitHubToken

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

class TaskSetTarget(BaseModel):
    target_file: str      # e.g. "package.json"

class TaskDiffIn(BaseModel):
    diff: str

class PublishIn(BaseModel):
    title: str | None = None
    body: str | None = None

class WorkBranchIn(BaseModel):
    work_branch: str



# ----- Routes -----



@router.post("/{task_id}/work-branch")
def set_work_branch(task_id: int, payload: WorkBranchIn, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.work_branch = payload.work_branch
    db.commit()
    return {"ok": True, "work_branch": task.work_branch}



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


@router.post("/{task_id}/start")
def start_task(task_id: int, db: Session = Depends(get_db)):
    user_id = 1  # dev for now

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "QUEUED":
        raise HTTPException(status_code=400, detail=f"Cannot start task in status {task.status}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # (Optional but recommended)
    if not user.github_login:
        raise HTTPException(status_code=400, detail="GitHub token not found for user")

    task.status = "RUNNING"
    db.commit()

    # ✅ pass user now
    start_task_container(task, user)

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

@router.post("/{task_id}/target")
def set_target_file(task_id: int, payload: TaskSetTarget, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.target_file = payload.target_file
    db.commit()
    return {"ok": True, "task_id": task.id, "target_file": task.target_file}


@router.post("/{task_id}/diff")
def save_diff(task_id: int, payload: TaskDiffIn, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.diff_text = payload.diff
    db.commit()
    return {"ok": True}

@router.get("/{task_id}/diff")
def get_diff(task_id: int, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task.id, "diff": task.diff_text or ""}


@router.post("/{task_id}/publish")
async def publish_task(task_id: int, payload: PublishIn | None = None, db: Session = Depends(get_db)):
    user_id = 1  # keep same dev approach

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.work_branch:
        raise HTTPException(status_code=400, detail="work_branch not set (agent did not push?)")

    # parse owner/repo from repo_full_name
    if not task.repo_full_name or "/" not in task.repo_full_name:
        raise HTTPException(status_code=400, detail="Invalid repo_full_name on task")

    owner, repo = task.repo_full_name.split("/", 1)

    # get user's github token from DB (same method you already use for repos/branches)
    # Example: user.github_access_token (adjust to your project)
    user = db.query(User).filter(User.id == user_id).first()
    token = get_token_for_user(user_id)
    if not user or not token:
        raise HTTPException(status_code=401, detail="GitHub token missing")

    title = (payload.title if payload and payload.title else f"Jules: Task {task.id}")
    body = (payload.body if payload and payload.body else (task.prompt or ""))

    async with httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30.0,
    ) as client:
        gh = GitHubClient(client)
        pr = await gh.create_pull_request(
            owner=owner,
            repo=repo,
            head=task.work_branch,     # e.g. "jules/task-1"
            base=task.branch,          # e.g. "main"
            title=title,
            body=body,
        )

    task.pr_url = pr.get("html_url")
    task.pr_number = pr.get("number")
    task.status = "COMPLETED"
    db.commit()

    return {
        "ok": True,
        "task_id": task.id,
        "work_branch": task.work_branch,
        "pr_url": task.pr_url,
        "pr_number": task.pr_number,
        "status": task.status,
    }