"""Ephemeral workspace management for workflow runs.

Workflows clone their target repo into a temp directory, do their work,
and clean up when done. This keeps workflow execution isolated from
the user's interactive workstream clones.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


def clone_repo(
    repo_url: str,
    branch: str = "main",
    dest: Optional[str] = None,
    depth: int = 1,
) -> str:
    """Clone a repo into a temp directory.

    Args:
        repo_url: Git remote URL.
        branch: Branch to clone.
        dest: Destination path (auto-generated if None).
        depth: Shallow clone depth (1 = latest commit only).

    Returns:
        Path to the cloned repo.
    """
    if dest is None:
        dest = tempfile.mkdtemp(prefix="maestro-ws-")

    cmd = ["git", "clone", "--branch", branch, "--depth", str(depth), repo_url, dest]
    logger.info(f"Cloning {repo_url} ({branch}) → {dest}")

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr}")

    return dest


def create_branch(repo_path: str, branch_name: str) -> None:
    """Create and checkout a new branch in the given repo."""
    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    logger.info(f"Created branch {branch_name} in {repo_path}")


@contextmanager
def workspace(
    repo_url: str,
    branch: str = "main",
    work_branch: Optional[str] = None,
):
    """Context manager: clone repo, optionally create work branch, clean up on exit.

    Usage:
        with workspace("https://github.com/org/repo.git", work_branch="feat/my-feature") as ws:
            # ws is the path to the cloned repo on the work branch
            run_build(ws)

    The clone is deleted when the context exits (unless MAESTRO_KEEP_WORKSPACE=1).
    """
    repo_path = clone_repo(repo_url, branch=branch)
    try:
        if work_branch:
            create_branch(repo_path, work_branch)
        yield repo_path
    finally:
        if os.environ.get("MAESTRO_KEEP_WORKSPACE") == "1":
            logger.info(f"Keeping workspace at {repo_path} (MAESTRO_KEEP_WORKSPACE=1)")
        else:
            logger.info(f"Cleaning up workspace {repo_path}")
            shutil.rmtree(repo_path, ignore_errors=True)


def push_branch(repo_path: str, branch: Optional[str] = None) -> None:
    """Push the current branch to origin."""
    cmd = ["git", "push", "-u", "origin"]
    if branch:
        cmd.append(branch)
    else:
        cmd.append("HEAD")

    r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git push failed: {r.stderr}")
    logger.info(f"Pushed branch from {repo_path}")
