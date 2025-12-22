# agent/main.py
import os
import subprocess
import sys
from pathlib import Path
import httpx

def post_log(backend_url: str, task_id: str, msg: str):
    try:
        httpx.post(f"{backend_url}/tasks/{task_id}/logs", json={"message": msg}, timeout=5.0)
    except Exception:
        pass  # don't crash agent if logging fails

def mark_complete(backend_url: str, task_id: str):
    try:
        httpx.post(f"{backend_url}/tasks/{task_id}/complete", timeout=5.0)
    except Exception:
        pass

def mark_fail(backend_url: str, task_id: str, reason: str):
    try:
        httpx.post(f"{backend_url}/tasks/{task_id}/fail", json={"reason": reason}, timeout=5.0)
    except Exception:
        pass


def run(cmd: str, cwd: str | None = None, allow_fail: bool = False):
    """Run a shell command and stream output."""
    print(f"\n$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        msg = f"Command failed with exit code {result.returncode}"
        if allow_fail:
            print("[WARN]", msg)
        else:
            print("[ERROR]", msg)
            sys.exit(result.returncode)


def main():
    try:
        repo_url = os.getenv("REPO_URL")
        branch = os.getenv("BRANCH", "main")
        task_id = os.getenv("TASK_ID", "unknown")
        backend_url = os.getenv("BACKEND_URL", "http://host.docker.internal:8000")

        print("=== Simple Agent v1 ===")
        print(f"TASK_ID: {task_id}")
        print(f"REPO_URL: {repo_url}")
        print(f"BRANCH: {branch}")

        if not repo_url:
            print("ERROR: REPO_URL not set")
            sys.exit(1)

        workspace = Path("/workspace")
        repo_dir = workspace / "repo"

        # Ensure workspace exists
        workspace.mkdir(parents=True, exist_ok=True)

        # 1. Clone repo (if folder already exists, we can delete or reuse; for now assume fresh container)
        post_log(backend_url, task_id, f"Cloning repo...")
        run(f"git clone {repo_url} {repo_dir}")
        post_log(backend_url, task_id, "Cloning completed.")


        # 2. Checkout branch
        post_log(backend_url, task_id, f"Checking out branch '{branch}'...")
        run(f"git checkout {branch}", cwd=str(repo_dir))
        post_log(backend_url, task_id, "Checkout completed.")


        print("\n=== Repo cloned & branch checked out ===")
        print(f"Repo path inside container: {repo_dir}")

        # 3. Simple tech detection
        package_json = repo_dir / "package.json"
        requirements_txt = repo_dir / "requirements.txt"

        if package_json.exists():
            print("\nDetected Node.js project (package.json found).")
            # 4. Install Node dependencies
            run("npm install", cwd=str(repo_dir))

            # 5. Try running tests (if they exist). We allow failure so agent doesn't crash completely.
            print("\nTrying to run 'npm test' (if defined)...")
            run("npm test", cwd=str(repo_dir), allow_fail=True)

        elif requirements_txt.exists():
            print("\nDetected Python project (requirements.txt found).")
            # 4. Install Python dependencies
            run("pip3 install -r requirements.txt", cwd=str(repo_dir))

            # 5. Try running pytest (if tests exist)
            print("\nTrying to run 'pytest' (if installed/tests exist)...")
            run("pytest", cwd=str(repo_dir), allow_fail=True)

        else:
            print("\nNo package.json or requirements.txt found.")
            print("Skipping dependency installation & tests for now.")

        print("\n=== Agent work complete (v1) ===")
        print("This is where future versions will run LLM planning, editing, and more.")
        mark_complete(backend_url, task_id)
    except Exception as e:
        mark_fail(backend_url, task_id, str(e))
        raise


if __name__ == "__main__":
    main()
