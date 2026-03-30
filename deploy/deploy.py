"""
One-command deploy: push to GitHub → update VPS → restart engine.

Usage:
    python deploy/deploy.py                    # deploy with auto-detected changes
    python deploy/deploy.py --message "fix X"  # custom commit message
    python deploy/deploy.py --no-commit        # just pull + restart on VPS (no push)

Requirements:
    pip install paramiko
    Set VPS_HOST, VPS_USER, VPS_PASSWORD in .env
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

VPS_HOST = os.environ.get("VPS_HOST", "")
VPS_USER = os.environ.get("VPS_USER", "Administrator")
VPS_PASSWORD = os.environ.get("VPS_PASSWORD", "")
ENGINE_DIR = r"C:\forex-engine"


def run_local(cmd: str, check: bool = True) -> str:
    """Run a command locally."""
    print(f"  [local] {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def run_remote(commands: list[str]) -> None:
    """Run commands on the VPS via SSH (paramiko)."""
    try:
        import paramiko
    except ImportError:
        print("ERROR: pip install paramiko (needed for SSH)")
        sys.exit(1)

    if not VPS_HOST or not VPS_PASSWORD:
        print("ERROR: Set VPS_HOST and VPS_PASSWORD in .env")
        sys.exit(1)

    print(f"\n  Connecting to {VPS_HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASSWORD, timeout=15)

    for cmd in commands:
        print(f"  [vps] {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        if out:
            print(f"         {out}")
        if err and "warning" not in err.lower():
            print(f"         STDERR: {err}")

    ssh.close()
    print("  VPS connection closed.\n")


def main():
    parser = argparse.ArgumentParser(description="Deploy forex-engine to VPS")
    parser.add_argument("--message", "-m", default=None, help="Commit message")
    parser.add_argument("--no-commit", action="store_true", help="Skip git push, just pull + restart")
    args = parser.parse_args()

    print("\n=== FOREX ENGINE DEPLOY ===\n")

    # Step 1: Push local changes to GitHub
    if not args.no_commit:
        status = run_local("git status --porcelain", check=False)
        if status:
            print("  Uncommitted changes detected — committing...")
            run_local("git add -A")
            msg = args.message or "Deploy update"
            run_local(f'git commit -m "{msg}"')
        else:
            print("  No local changes to commit.")

        print("  Pushing to GitHub...")
        run_local("git push")
    else:
        print("  Skipping git push (--no-commit)")

    # Step 2: Pull on VPS and restart engine
    print("\n  Updating VPS...")
    run_remote([
        f"cd {ENGINE_DIR} && git pull",
        f"cd {ENGINE_DIR} && pip install -r requirements.txt --quiet",
        # Kill existing engine process
        'taskkill /F /FI "WINDOWTITLE eq forex-engine*" 2>nul || echo "No engine running"',
        # Restart via Task Scheduler
        'schtasks /Run /TN "Forex Engine" 2>nul || echo "Task not found — start manually"',
    ])

    print("=== DEPLOY COMPLETE ===")
    print(f"  Dashboard: http://{VPS_HOST}:8080")
    print()


if __name__ == "__main__":
    main()
