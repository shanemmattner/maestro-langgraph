"""Issue-to-PR workflow graph — fetch -> decompose -> execute -> review -> commit_pr.

Flow: START -> fetch_issue -> decompose -> execute -> review -> [commit_pr?] -> END

The commit_pr node runs only on APPROVE or NITS verdict.
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
from langgraph_maestro.core.config import load_config, workflow_config_path
from langgraph_maestro.core.runner import run_workflow as _run_workflow
from .state import IssueToPRState
from .nodes import fetch_issue_node, decompose_node, execute_node, review_node, commit_pr_node, _cleanup_worktree

logger = logging.getLogger(__name__)


def _should_commit(state: IssueToPRState) -> str:
    """Route after review: commit on APPROVE/NITS, cleanup on REJECT or errors."""
    if state.get("errors"):
        return "cleanup"
    verdict = state.get("verdict", "REJECT")
    return "commit_pr" if verdict in ("APPROVE", "NITS") else "cleanup"


def _cleanup_worktree_node(state: IssueToPRState) -> dict:
    """Clean up worktree when workflow ends without committing (REJECT/error)."""
    repo_path = state.get("repo_path", ".")
    worktree_path = state.get("worktree_path")
    if worktree_path:
        _cleanup_worktree(repo_path, worktree_path)
        logger.info("worktree_cleaned_on_reject", extra={"worktree": worktree_path})
    return {"phase": "cleanup"}


def _should_decompose(state: IssueToPRState) -> str:
    """Route after fetch_issue: proceed to decompose if no errors, otherwise end."""
    return 'end' if state.get('errors') else 'decompose'


def build_graph(config_path: str = workflow_config_path(__file__)):
    """Build and compile the issue_to_pr LangGraph workflow."""
    logger.info("graph_compile_start")

    graph = StateGraph(IssueToPRState)

    graph.add_node("fetch_issue", fetch_issue_node)
    graph.add_node("decompose", decompose_node)
    graph.add_node("execute", execute_node)
    graph.add_node("review", review_node)
    graph.add_node("commit_pr", commit_pr_node)
    graph.add_node("cleanup", _cleanup_worktree_node)

    graph.set_entry_point("fetch_issue")
    graph.add_conditional_edges('fetch_issue', _should_decompose, {'decompose': 'decompose', 'end': END})
    graph.add_edge("decompose", "execute")
    graph.add_edge("execute", "review")
    graph.add_conditional_edges("review", _should_commit, {"commit_pr": "commit_pr", "cleanup": "cleanup"})
    graph.add_edge("commit_pr", END)
    graph.add_edge("cleanup", END)

    compiled = graph.compile(checkpointer=get_checkpointer())
    logger.info("graph_compile_done")
    return compiled


def run_workflow(
    issue_url: str,
    repo_path: str,
    config_path: str = workflow_config_path(__file__),
) -> dict:
    """Run the issue_to_pr workflow end-to-end.

    Args:
        issue_url: GitHub issue URL (e.g. https://github.com/owner/repo/issues/42)
        repo_path: Local path to the repository to modify.
        config_path: Path to the workflow config YAML.

    Returns:
        Final state dict with pr_url, verdict, subtasks, and execution log.
    """
    graph = build_graph(config_path)
    thread_id = f"issue-to-pr-{issue_url[-20:]}"
    initial_state = {
        "issue_url": issue_url,
        "repo_path": repo_path,
        "config_path": config_path,
    }
    return _run_workflow("issue_to_pr", graph, initial_state, thread_id)
