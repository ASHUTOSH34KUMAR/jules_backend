# agent/main.py
import os
import subprocess
import sys
from pathlib import Path
import base64

import httpx
from openai import OpenAI


# ----------------------------
# Backend reporting helpers
# ----------------------------
def post_log(backend_url: str | None, task_id: str, msg: str):
    """Append a log line to backend. Never crash agent if backend not reachable."""
    if not backend_url:
        return
    try:
        httpx.post(
            f"{backend_url}/tasks/{task_id}/logs",
            json={"message": msg},
            timeout=5.0,
        )
    except Exception:
        pass


def mark_complete(backend_url: str | None, task_id: str):
    if not backend_url:
        return
    try:
        httpx.post(f"{backend_url}/tasks/{task_id}/complete", timeout=5.0)
    except Exception:
        pass


def mark_fail(backend_url: str | None, task_id: str, reason: str):
    if not backend_url:
        return
    try:
        httpx.post(
            f"{backend_url}/tasks/{task_id}/fail",
            json={"reason": reason},
            timeout=5.0,
        )
    except Exception:
        pass


def post_diff(backend_url: str | None, task_id: str, diff_text: str):
    """Save git diff to backend."""
    if not backend_url:
        return
    try:
        httpx.post(
            f"{backend_url}/tasks/{task_id}/diff",
            json={"diff": diff_text},
            timeout=10.0,
        )
    except Exception:
        pass


# ----------------------------
# Shell helpers
# ----------------------------
def run(cmd: str, cwd: str | None = None, allow_fail: bool = False):
    print(f"\n$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        msg = f"Command failed ({result.returncode}): {cmd}\nSTDERR: {result.stderr.strip()}"
        if allow_fail:
            print("[WARN]", msg)
            return
        raise RuntimeError(msg)


def run_capture(cmd: str, cwd: str | None = None) -> str:
    """Run a shell command and capture stdout as text."""
    print(f"\n$ {cmd}")
    return subprocess.check_output(cmd, shell=True, cwd=cwd, text=True)


# ----------------------------
# LLM edit helper
# ----------------------------
def llm_rewrite_file(prompt: str, file_path: str, original: str) -> str:
    """
    Ask model to output the full updated file content ONLY.
    The agent will overwrite the file with this output.
    """
    client = OpenAI()

    instructions = f"""
You are an expert software engineer.

Rewrite ONLY the file content for: {file_path}

Rules:
- Output ONLY the updated full file content. No markdown fences. No explanations.
- Keep behavior the same unless the prompt asks otherwise.
- Make minimal, safe improvements: refactor, add comments, small bug fixes.
- Ensure Python syntax is valid.
"""

    user_input = f"""
TASK PROMPT:
{prompt}

CURRENT FILE CONTENT:
{original}
"""

    resp = client.responses.create(
        model="gpt-4o-mini",
        instructions=instructions,
        input=user_input,
    )
    return resp.output_text.strip()

def post_work_branch(backend_url: str | None, task_id: str, work_branch: str):
    if not backend_url:
        return
    try:
        httpx.post(
            f"{backend_url}/tasks/{task_id}/work-branch",
            json={"work_branch": work_branch},
            timeout=10.0
        )
    except Exception:
        pass

def getenv_b64(name: str) -> str:
    val = os.getenv(name, "")
    if not val:
        return ""
    return base64.b64decode(val.encode("ascii")).decode("utf-8")
# ----------------------------
# Target file resolution
# ----------------------------
def resolve_target_file(repo_dir: Path, target_file: str) -> Path | None:
    """
    Resolve target file path robustly.
    Supports user passing:
      - "Snake.py"
      - "main/Snake.py"  (we strip leading "main/" if needed)
      - Windows slashes
    """
    if not target_file:
        return None

    normalized = target_file.replace("\\", "/").lstrip("/")

    candidates = [repo_dir / normalized]

    if normalized.startswith("main/"):
        candidates.append(repo_dir / normalized[len("main/"):])

    for p in candidates:
        if p.exists() and p.is_file():
            return p

    return None


# ----------------------------
# Main agent workflow
# ----------------------------
def main():
    backend_url = os.getenv("BACKEND_URL", "http://host.docker.internal:8000")
    repo_url = os.getenv("REPO_URL")
    branch = os.getenv("BRANCH", "main")
    task_id = os.getenv("TASK_ID", "unknown")

    task_prompt = getenv_b64("TASK_PROMPT_B64").strip()
    target_file = getenv_b64("TARGET_FILE_B64").strip()

    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    repo_full_name = os.getenv("REPO_FULL_NAME", "").strip()

    if not github_token:
        raise RuntimeError("GITHUB_TOKEN not set (needed to push branch)")
    if not repo_full_name or "/" not in repo_full_name:
        raise RuntimeError("REPO_FULL_NAME not set or invalid")

    post_log(backend_url, task_id, f"DEBUG: TARGET_FILE='{target_file}'")
    post_log(backend_url, task_id, f"DEBUG: TASK_PROMPT length={len(task_prompt)}")
    post_log(backend_url, task_id, f"DEBUG: OPENAI_API_KEY set={bool(os.getenv('OPENAI_API_KEY'))}")

    print("=== Jules Agent v2 (LLM single-file edit) ===")
    print(f"TASK_ID: {task_id}")
    print(f"REPO_URL: {repo_url}")
    print(f"BRANCH: {branch}")
    print(f"BACKEND_URL: {backend_url}")
    print(f"TARGET_FILE: {target_file}")

    if not repo_url:
        raise RuntimeError("REPO_URL not set")

    if not target_file:
        raise RuntimeError("TARGET_FILE not set (backend must set it before starting)")

    if not task_prompt:
        raise RuntimeError("TASK_PROMPT not set (backend must pass task.prompt into container)")

    workspace = Path("/workspace")
    repo_dir = workspace / "repo"
    workspace.mkdir(parents=True, exist_ok=True)

    try:
        # 1) Clone
        post_log(backend_url, task_id, f"Cloning repo: {repo_url}")
        run(f"git clone {repo_url} {repo_dir}")
        post_log(backend_url, task_id, "Clone completed.")

        # 2) Checkout branch
        post_log(backend_url, task_id, f"Checking out branch: {branch}")
        run(f"git checkout {branch}", cwd=str(repo_dir))
        post_log(backend_url, task_id, "Checkout completed.")

        # 3) Resolve target file and read it
        file_path = resolve_target_file(repo_dir, target_file)
        if not file_path:
            raise RuntimeError(f"Target file not found in repo: {target_file}")

        rel_path = str(file_path.relative_to(repo_dir)).replace("\\", "/")
        post_log(backend_url, task_id, f"Target file resolved: {rel_path}")

        post_log(backend_url, task_id, f"Reading file: {rel_path}")
        original = file_path.read_text(encoding="utf-8", errors="replace")

        # 4) LLM rewrite
        post_log(backend_url, task_id, "Calling LLM to rewrite file...")
        updated = llm_rewrite_file(task_prompt, rel_path, original)

        if not updated.strip():
            raise RuntimeError("LLM returned empty content")

        # Optional guard: if model output is identical, still ok
        if updated.strip() == original.strip():
            post_log(backend_url, task_id, "LLM output identical to original (no changes). Continuing.")

        # 5) Write file
        post_log(backend_url, task_id, f"Writing updated file: {rel_path}")
        file_path.write_text(updated, encoding="utf-8")

        # 6) Quick Python syntax check for the changed file
        post_log(backend_url, task_id, "Running python syntax check (py_compile)...")
        run(f"python3 -m py_compile {rel_path}", cwd=str(repo_dir))
        post_log(backend_url, task_id, "py_compile passed.")

        # 7) Optional: keep your dependency/test detection (best effort)
        #    This is safe to keep minimal Jules-like behavior.
        package_json = repo_dir / "package.json"
        requirements_txt = repo_dir / "requirements.txt"

        if package_json.exists():
            post_log(backend_url, task_id, "Detected Node.js project. Running npm install...")
            run("npm install", cwd=str(repo_dir), allow_fail=True)
            post_log(backend_url, task_id, "npm install finished (may have warnings).")

            post_log(backend_url, task_id, "Running npm test (best effort)...")
            run("npm test", cwd=str(repo_dir), allow_fail=True)
            post_log(backend_url, task_id, "npm test finished (best effort).")

        elif requirements_txt.exists():
            post_log(backend_url, task_id, "Detected Python project. Installing requirements (best effort)...")
            run("pip3 install -r requirements.txt", cwd=str(repo_dir), allow_fail=True)
            post_log(backend_url, task_id, "pip install finished (best effort).")

            post_log(backend_url, task_id, "Running pytest (best effort)...")
            run("pytest", cwd=str(repo_dir), allow_fail=True)
            post_log(backend_url, task_id, "pytest finished (best effort).")

        else:
            post_log(backend_url, task_id, "No package.json/requirements.txt detected. Skipping deps/tests.")

        # 8) Capture git diff and send to backend
        post_log(backend_url, task_id, "Capturing git diff...")
        diff_text = run_capture("git diff", cwd=str(repo_dir))

        if diff_text.strip():
            post_diff(backend_url, task_id, diff_text)
            post_log(backend_url, task_id, "Diff saved to backend.")
        else:
            post_log(backend_url, task_id, "No diff produced (file may be unchanged). Saving empty diff.")
            post_diff(backend_url, task_id, "")
        
        post_log(backend_url, task_id, "Configuring git user identity...")
        run('git config user.email "jules-agent@local"', cwd=str(repo_dir))
        run('git config user.name "Jules Agent"', cwd=str(repo_dir))

        # 9) Create branch + commit
        work_branch = f"jules/task-{task_id}"
        post_log(backend_url, task_id, f"Creating work branch: {work_branch}")
        run(f"git checkout -b {work_branch}", cwd=str(repo_dir))

        post_log(backend_url, task_id, f"Staging file: {rel_path}")
        run(f"git add {rel_path}", cwd=str(repo_dir))

        post_work_branch(backend_url, task_id, work_branch)
        post_log(backend_url, task_id, "work_branch saved to backend.")
        
        status = run_capture("git status --porcelain", cwd=str(repo_dir))
        if not status.strip():
            post_log(backend_url, task_id, "No changes detected after edit. Skipping commit/push/PR.")
            post_diff(backend_url, task_id, "")  # optional
            mark_complete(backend_url, task_id)
            return


        commit_msg = f"Jules: Task {task_id}"
        post_log(backend_url, task_id, f"Committing changes: {commit_msg}")
        run(f'git commit -m "{commit_msg}"', cwd=str(repo_dir), allow_fail=False)

        # Save work_branch to backend by reusing logs OR add a small endpoint later.
        # For now, agent will call /publish and backend will use task.work_branch from DB.
        # So: we should also store work_branch on task BEFORE /start, OR add endpoint to set it.

        # 10) Push branch using token
        owner, repo = repo_full_name.split("/", 1)
        remote_url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo}.git"

        post_log(backend_url, task_id, "Setting authenticated remote URL for push...")
        run(f"git remote set-url origin {remote_url}", cwd=str(repo_dir))

        post_log(backend_url, task_id, f"Pushing branch: {work_branch}")
        run(f"git push -u origin {work_branch}", cwd=str(repo_dir))
        post_log(backend_url, task_id, "Push completed.")


        post_log(backend_url, task_id, "Requesting backend to create PR (/publish)...")
        httpx.post(f"{backend_url}/tasks/{task_id}/publish", json={}, timeout=30.0)
        post_log(backend_url, task_id, "PR created (or already exists).")

  
        # 11) Mark complete
        post_log(backend_url, task_id, "Task completed successfully.")
        mark_complete(backend_url, task_id)

        print("\n=== Agent done (v2) ===")

    except Exception as e:
        err = str(e)
        post_log(backend_url, task_id, f"[ERROR] {err}")
        mark_fail(backend_url, task_id, err)
        raise


if __name__ == "__main__":
    main()
