# backend/services/orchestrator.py
import subprocess
from backend.models import Task

def build_repo_url(repo_full_name: str) -> str:
    """
    Convert 'owner/repo' into https Git URL.
    Example: 'abhinavsiingh/Unimarket' -> 'https://github.com/abhinavsiingh/Unimarket.git'
    """
    return f"https://github.com/{repo_full_name}.git"


def start_task_container(task: Task):
    """
    Start a Docker container for the given Task.
    Non-blocking: returns immediately while container keeps running in background.
    """
    repo_url = build_repo_url(task.repo_full_name)

    cmd = [
        "docker", "run", "--rm",
        "-e", f"TASK_ID={task.id}",
        "-e", f"REPO_URL={repo_url}",
        "-e", f"BRANCH={task.branch}",
        "jules-agent:dev",
    ]

    print("Starting Docker container for task:", task.id)
    print("Command:", " ".join(cmd))

    # Run in background so API doesn't block
    subprocess.Popen(cmd)
