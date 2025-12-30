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

class PlanOut(BaseModel):
    task_id: int
    status: str
    plan: str


class TaskLogAppend(BaseModel):
    message: str

class TaskResponse(BaseModel):
    id: int
    repo_full_name: str
    branch: str
    base_commit_sha: str | None
    prompt: str
    status: str

    target_file: str | None = None
    work_branch: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    diff_text: str | None = ""
    log_text: str | None = ""
    plan_text: str | None = None
    plan_generated_by: str | None = None

    class Config:
        from_attributes = True

class TaskSetTarget(BaseModel):
    target_file: str      # e.g. "package.json"

class TaskDiffIn(BaseModel):
    diff: str

class PublishIn(BaseModel):
    title: str | None = None
    body: str | None = None

class WorkBranchIn(BaseModel):
    work_branch: str

class StatusIn(BaseModel):
    status: str

class PlanOut(BaseModel):
    plan: str

class PlanIn(BaseModel):
    force: bool = False

# ----- Routes -----

# Note: LLM-powered plan generation implemented further down (single /plan endpoint).

@router.post("/{task_id}/status")
def set_status(task_id: int, payload: StatusIn, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = payload.status
    db.commit()
    return {"ok": True, "status": task.status}





@router.post("/{task_id}/work-branch")
def set_work_branch(task_id: int, payload: WorkBranchIn, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.work_branch = payload.work_branch
    db.commit()
    return {"ok": True, "work_branch": task.work_branch}

@router.post("/{task_id}/approve")
def approve_task(task_id: int, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Allow approving when plan is PLANNED or PLAN_READY (LLM-generated plans produce PLAN_READY)
    if task.status not in ("PLANNED", "PLAN_READY"):
        raise HTTPException(status_code=400, detail=f"Cannot approve task in status {task.status}")

    task.status = "APPROVED"
    db.commit()
    return {"ok": True, "status": task.status}


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

    if task.status != "APPROVED":
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
    user_id = 1

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Option B gate: PR only after PUSH
    if task.status != "PUSHED":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create PR until branch is pushed. Current status: {task.status}"
        )

    if not task.work_branch:
        raise HTTPException(status_code=400, detail="work_branch not set")

    if not task.repo_full_name or "/" not in task.repo_full_name:
        raise HTTPException(status_code=400, detail="Invalid repo_full_name on task")

    owner, repo = task.repo_full_name.split("/", 1)

    token = get_token_for_user(user_id)
    if not token:
        raise HTTPException(status_code=401, detail="GitHub token missing")

    title = payload.title if payload and payload.title else f"Jules: Task {task.id}"
    body = payload.body if payload and payload.body else (task.prompt or "")

    # ✅ simplest correct usage with your GitHubClient
    gh = GitHubClient(token)

    # Pre-check: ensure work_branch has commits ahead of base branch. This avoids
    # a confusing GitHub 422 when there are no commits between branches.
    try:
        cmp = await gh.compare_commits(owner, repo, task.branch, task.work_branch)
        ahead_by = cmp.get("ahead_by", 0) if isinstance(cmp, dict) else 0
    except Exception as e:
        # If compare fails for some reason, surface as a helpful error
        raise HTTPException(status_code=400, detail=f"Failed to compare branches: {e}") from e

    if ahead_by == 0:
        # Provide more helpful debug info: include branch tip SHAs and compare status
        try:
            base_branch_data = await gh.get_branch(owner, repo, task.branch)
            work_branch_data = await gh.get_branch(owner, repo, task.work_branch)
            base_sha = base_branch_data.get("commit", {}).get("sha")
            work_sha = work_branch_data.get("commit", {}).get("sha")
            cmp_status = cmp.get("status", "<unknown>") if isinstance(cmp, dict) else "<unknown>"
            detail = (
                f"No commits between {task.branch} (sha={base_sha}) and {task.work_branch} (sha={work_sha}). "
                f"Compare status: {cmp_status}. Make sure you pushed commits to the work branch before creating a PR."
            )
        except Exception:
            detail = (
                f"No commits between {task.branch} and {task.work_branch}. "
                "Make sure you pushed commits to the work branch before creating a PR."
            )
        raise HTTPException(status_code=400, detail=detail)

    try:
        pr = await gh.create_pull_request(
            owner=owner,
            repo=repo,
            head=task.work_branch,
            base=task.branch,
            title=title,
            body=body,
        )
    except Exception as e:
        # Include GitHub error details in the API response for easier debugging
        raise HTTPException(status_code=400, detail=f"Failed to create PR: {e}") from e

    task.pr_url = pr.get("html_url")
    task.pr_number = pr.get("number")
    task.status = "PR_CREATED"
    db.commit()

    return {
        "ok": True,
        "task_id": task.id,
        "work_branch": task.work_branch,
        "pr_url": task.pr_url,
        "pr_number": task.pr_number,
        "status": task.status,
    }


@router.post("/{task_id}/plan", response_model=PlanOut)
async def generate_plan(task_id: int, payload: PlanIn | None = None, db: Session = Depends(get_db)):
    """Generate a plan using an LLM. If `payload.force` is True, re-generate the plan even if not in a planning-ready state."""
    import os
    import openai

    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    allow = task.status in ("QUEUED", "PLAN_READY") or (payload and payload.force)
    if not allow:
        raise HTTPException(status_code=400, detail=f"Cannot plan task in status {task.status}")

    # Ensure we have a target file (we can still allow auto-detect in the future)
    if not task.target_file:
        raise HTTPException(status_code=400, detail="Target file not set")

    # Fetch target file contents from GitHub (if possible)
    file_content = None
    try:
        owner, repo = task.repo_full_name.split("/", 1)
        token = get_token_for_user(user_id)
        if token:
            gh = GitHubClient(token)
            try:
                file_content = await gh.get_file(owner, repo, task.target_file, ref=task.branch)
            except Exception:
                file_content = None
    except Exception:
        file_content = None

    # Call OpenAI to generate a structured plan
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured (OPENAI_API_KEY)")
    openai.api_key = openai_key

    system_prompt = (
        "You are an assistant that writes concise, step-by-step implementation plans to modify a file in a repository. "
        "Produce a clear numbered plan (1., 2., 3., ...). If file contents are provided, inspect them and highlight risky changes. "
        "Keep the plan actionable and small — 5-12 steps."
    )

    user_lines = [
        f"Repo: {task.repo_full_name}",
        f"Base branch: {task.branch}",
        f"Target file: {task.target_file}",
        "",
        f"User prompt: {task.prompt}",
    ]
    if file_content:
        # Truncate if very large
        txt = file_content if len(file_content) < 10000 else file_content[:10000] + "\n... [truncated]"
        user_lines += ["", "File content:", txt]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_lines)},
    ]

    model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

    # Support both new (>1.0.0) OpenAI python client and the older interface
    plan_text = None
    last_err = None
    try:
        # New client: `from openai import OpenAI; client = OpenAI()`
        from openai import OpenAI as OpenAIClient
        client = OpenAIClient(api_key=openai_key)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=600,
            temperature=0.2,
        )
        # Try a few ways to extract the assistant content
        try:
            plan_text = resp.choices[0].message.content
        except Exception:
            try:
                plan_text = resp.choices[0]["message"]["content"]
            except Exception:
                plan_text = None
    except Exception as e:
        last_err = e

    if not plan_text:
        try:
            # Fallback to older openai lib usage
            import openai as old_openai
            old_openai.api_key = openai_key
            resp = old_openai.ChatCompletion.create(
                model=model,
                messages=messages,
                max_tokens=600,
                temperature=0.2,
            )
            plan_text = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            # Prefer the newer exception if present, otherwise the fallback's
            detail = f"LLM request failed: {last_err or e}"
            raise HTTPException(status_code=500, detail=detail) from (last_err or e)

    # Save plan and mark ready for approval
    task.plan_text = plan_text
    task.plan_generated_by = f"openai:{model}"
    task.status = "PLAN_READY"
    db.commit()

    return {"plan": plan_text}

@router.post("/{task_id}/plan/approve")
def approve_plan(task_id: int, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "PLAN_READY":
        raise HTTPException(status_code=400, detail=f"Cannot approve plan in status {task.status}")

    task.status = "APPROVED"
    db.commit()
    return {"ok": True, "task_id": task.id, "status": task.status}


@router.post("/{task_id}/push")
def push_task_branch(task_id: int, db: Session = Depends(get_db)):
    user_id = 1
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "READY_FOR_REVIEW":
        raise HTTPException(status_code=400, detail=f"Cannot push in status {task.status}")

    if not task.work_branch:
        raise HTTPException(status_code=400, detail="work_branch not set yet (agent didn’t create it)")

    user = db.query(User).filter(User.id == user_id).first()
    token = get_token_for_user(user_id)
    if not user or not token:
        raise HTTPException(status_code=401, detail="GitHub token missing")

    # Mark status first
    task.status = "PUSHING"
    db.commit()

    # Spawn container in PUSH mode
    start_task_container(task, user, mode="push")

    return {"ok": True, "task_id": task.id, "status": task.status, "work_branch": task.work_branch}
