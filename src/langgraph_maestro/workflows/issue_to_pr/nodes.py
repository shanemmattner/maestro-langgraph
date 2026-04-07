"""Issue-to-PR workflow nodes — fetch, decompose, execute, review, commit_pr.

Uses core/nodes/ factories for shared logic, with worktree isolation
wrapping execute and commit_pr for concurrent workflow safety.
"""

import logging
import shutil
import subprocess
import tempfile

from langgraph_maestro.nodes import make_decompose_node, make_execute_node, make_review_node
from langgraph_maestro.nodes.fetch_issue import make_fetch_issue_node
from langgraph_maestro.nodes.commit_pr import make_commit_pr_node
from langgraph_maestro.core.schemas import DecomposeOutput
from .state import IssueToPRState
from langgraph_maestro.core.config import workflow_config_path
from pathlib import Path

logger = logging.getLogger(__name__)


# --- Git worktree helpers ---

def _run(cmd: list[str], cwd: str | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, check=True, capture_output=capture)


def _create_worktree(repo_path: str, branch_name: str) -> str:
    """Create an isolated git worktree for this workflow run."""
    worktree_dir = tempfile.mkdtemp(prefix=f"maestro-wt-{branch_name}-")
    try:
        _run(["git", "worktree", "add", "-b", branch_name, worktree_dir], cwd=repo_path)
    except subprocess.CalledProcessError:
        shutil.rmtree(worktree_dir, ignore_errors=True)
        worktree_dir = tempfile.mkdtemp(prefix=f"maestro-wt-{branch_name}-")
        _run(["git", "worktree", "add", worktree_dir, branch_name], cwd=repo_path)
    logger.info("worktree_created", extra={"worktree": worktree_dir, "branch": branch_name})
    return worktree_dir


def _cleanup_worktree(repo_path: str, worktree_path: str) -> None:
    """Remove a git worktree and its directory."""
    try:
        _run(["git", "worktree", "remove", "--force", worktree_path], cwd=repo_path)
        logger.info("worktree_removed", extra={"worktree": worktree_path})
    except Exception as exc:
        logger.warning("worktree_cleanup_failed", extra={"error": str(exc), "worktree": worktree_path})
        shutil.rmtree(worktree_path, ignore_errors=True)


# --- Shared nodes from core/nodes/ factories ---

decompose_node = make_decompose_node(
    config_path_default=workflow_config_path(__file__),
    schema_class=DecomposeOutput,
    prompts_dir=str(Path(__file__).parent / "prompts"),
)


# Base execute node from factory (used inside worktree wrapper)
_base_execute_node = make_execute_node(
    config_path_default=workflow_config_path(__file__),
    prompts_dir=str(Path(__file__).parent / "prompts"),
)

# Base review node from factory
_base_review_node = make_review_node(
    config_path_default=workflow_config_path(__file__),
    prompts_dir=str(Path(__file__).parent / "prompts"),
)

# Base commit_pr node from factory
_base_commit_pr_node = make_commit_pr_node()


# --- Worktree-wrapped nodes ---

def execute_node(state: dict) -> dict:
    """Execute subtasks in an isolated git worktree.

    Creates a worktree, redirects cwd for the base execute node,
    then returns the worktree_path in state for downstream nodes.
    """
    repo_path = state.get("repo_path")
    if not repo_path:
        return {"errors": ["repo_path is required"], "phase": "execute"}

    branch_name = state.get("branch_name", "issue-fix")

    # Create isolated worktree
    worktree_path = _create_worktree(repo_path, branch_name)

    # Override cwd so execute runs in worktree
    patched_state = dict(state)
    patched_state["cwd"] = worktree_path

    result = _base_execute_node(patched_state)
    result["worktree_path"] = worktree_path
    return result


def review_node(state: dict) -> dict:
    """Review node that prefers worktree_path over repo_path for file access."""
    patched_state = dict(state)
    if state.get("worktree_path"):
        patched_state["cwd"] = state["worktree_path"]
    return _base_review_node(patched_state)


def commit_pr_node(state: dict) -> dict:
    """Commit and push from worktree, then clean up."""
    repo_path = state.get("repo_path", ".")
    worktree_path = state.get("worktree_path")

    # Patch state so commit_pr uses worktree as repo_path
    patched_state = dict(state)
    if worktree_path:
        patched_state["repo_path"] = worktree_path

    try:
        result = _base_commit_pr_node(patched_state)
        return result
    finally:
        if worktree_path:
            _cleanup_worktree(repo_path, worktree_path)


# --- Workflow-specific nodes ---

fetch_issue_node = make_fetch_issue_node()
