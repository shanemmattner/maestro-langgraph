"""PR Review workflow graph — fetch -> analyze -> synthesize.

Flow: START -> fetch_pr -> fan_out_reviewers (Send) -> reviewer_node (parallel) 
       -> collect_reviews -> synthesize -> [conditional]
       - If verdict in (REQUEST_CHANGES, REJECT) -> escalate -> END
       - If verdict APPROVE -> END
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
from langgraph_maestro.core.config import load_config, workflow_config_path
from langgraph_maestro.core.runner import run_workflow as _run_workflow
from .state import PRReviewState
from .nodes import (
    fetch_pr_node,
    fan_out_reviewers,
    reviewer_node,
    collect_reviews,
    synthesize_node,
    escalated_review_node,
)

logger = logging.getLogger(__name__)


def _should_escalate(state: PRReviewState) -> str:
    """Determine if review should be escalated based on verdict.
    
    Returns:
        "escalate" if verdict is REQUEST_CHANGES or REJECT
        "approved" otherwise
    """
    verdict = state.get("verdict", "").upper()
    config_path = state.get("config_path", workflow_config_path(__file__))
    
    try:
        config = load_config(config_path)
        escalation_config = config.get("escalation", {})
        enabled = escalation_config.get("enabled", True)
        trigger_verdicts = escalation_config.get("trigger_verdicts", ["REQUEST_CHANGES", "REJECT"])
    except Exception:
        enabled = True
        trigger_verdicts = ["REQUEST_CHANGES", "REJECT"]
    
    if not enabled:
        logger.info("escalation_disabled_skipping")
        return "approved"
    
    if verdict in trigger_verdicts:
        logger.info("escalation_triggered", extra={"verdict": verdict})
        return "escalate"
    
    return "approved"


def build_graph(config_path: str = workflow_config_path(__file__)):
    """Build and compile the pr_review LangGraph workflow."""
    logger.info("graph_compile_start")

    graph = StateGraph(PRReviewState)

    # Add nodes
    graph.add_node("fetch_pr", fetch_pr_node)
    graph.add_node("reviewer_node", reviewer_node)
    graph.add_node("collect_reviews", collect_reviews)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("escalated_review", escalated_review_node)

    # Set entry point
    graph.set_entry_point("fetch_pr")
    
    # Fan-out to parallel reviewer nodes using Send() API
    graph.add_conditional_edges(
        "fetch_pr",
        fan_out_reviewers,
        ["reviewer_node"]
    )
    
    # After parallel reviewers complete, collect results
    graph.add_edge("reviewer_node", "collect_reviews")
    graph.add_edge("collect_reviews", "synthesize")
    
    # Add conditional edge: escalate on REJECT/REQUEST_CHANGES, else approved
    graph.add_conditional_edges(
        "synthesize",
        _should_escalate,
        {
            "escalate": "escalated_review",
            "approved": END,
        }
    )
    
    # After escalation, return final result (use escalation verdict as final)
    graph.add_edge("escalated_review", END)

    compiled = graph.compile(checkpointer=get_checkpointer())
    logger.info("graph_compile_done")
    return compiled


def run_workflow(
    pr_url: str,
    repo_path: str = None,
    config_path: str = workflow_config_path(__file__),
) -> dict:
    """Run the pr_review workflow end-to-end.

    Args:
        pr_url: GitHub PR URL (e.g. https://github.com/owner/repo/pull/42)
        repo_path: Local path to the repository (optional, for context).
        config_path: Path to the workflow config YAML.

    Returns:
        Final state dict with verdict, review_summary, issues, and findings.
    """
    graph = build_graph(config_path)
    thread_id = f"pr-review-{pr_url[-20:]}"
    initial_state = {
        "pr_url": pr_url,
        "repo_path": repo_path,
        "config_path": config_path,
    }
    result = _run_workflow("pr_review", graph, initial_state, thread_id)

    # Use escalation verdict if review was escalated, otherwise use synthesize verdict
    result["verdict"] = result.get("escalation_verdict", result.get("verdict"))
    result["review_summary"] = result.get("escalation_summary", result.get("review_summary"))
    return result
