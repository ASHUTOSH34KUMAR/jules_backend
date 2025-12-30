# backend/services/orchestrator.py
import os
import subprocess
import base64
from backend.models import Task
from backend.services.github_token_service import get_token_for_user

def build_repo_url(repo_full_name: str) -> str:
    return f"https://github.com/{repo_full_name}.git"

def start_task_container(task: Task, user, mode:str = "execute"):
    token = get_token_for_user(user.id)
    if not token:
        raise RuntimeError(f"No GitHub access token found for user_id={user.id}. Please login again.")

    repo_url = build_repo_url(task.repo_full_name)

    prompt_b64 = base64.b64encode((task.prompt or "").encode("utf-8")).decode("ascii")
    target_b64 = base64.b64encode((task.target_file or "").encode("utf-8")).decode("ascii")

    cmd = [
        "docker", "run", "--rm",
        "-e", f"TASK_ID={task.id}",
        "-e", f"REPO_URL={repo_url}",
        "-e", f"BRANCH={task.branch}",
        "-e", f"TASK_PROMPT_B64={prompt_b64}",
        "-e", f"TARGET_FILE_B64={target_b64}",
        "-e", "BACKEND_URL=http://host.docker.internal:8000",
        "-e", f"GITHUB_TOKEN={token}",
        "-e", f"MODE={mode}",
        "-e", f"REPO_FULL_NAME={task.repo_full_name}",
        "-e", f"OPENAI_API_KEY={os.getenv('OPENAI_API_KEY','')}",
        # Pass work branch when available (used by push mode)
        "-e", f"WORK_BRANCH={task.work_branch or ''}",
        "jules-agent:dev",
    ]

    print(f"Starting Docker container for task: {task.id} mode={mode} work_branch={task.work_branch}")
    subprocess.Popen(cmd)
