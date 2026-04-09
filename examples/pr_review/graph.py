"""PR Review workflow graph."""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
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
    verdict = state.get("verdict", "").upper()
    trigger_verdicts = ["REQUEST_CHANGES", "REJECT"]
    if verdict in trigger_verdicts:
        return "escalate"
    return "approved"


def build_graph():
    graph = StateGraph(PRReviewState)

    graph.add_node("fetch_pr", fetch_pr_node)
    graph.add_node("reviewer_node", reviewer_node)
    graph.add_node("collect_reviews", collect_reviews)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("escalated_review", escalated_review_node)

    graph.set_entry_point("fetch_pr")

    graph.add_conditional_edges("fetch_pr", fan_out_reviewers, ["reviewer_node"])
    graph.add_edge("reviewer_node", "collect_reviews")
    graph.add_edge("collect_reviews", "synthesize")

    graph.add_conditional_edges("synthesize", _should_escalate, {"escalate": "escalated_review", "approved": END})
    graph.add_edge("escalated_review", END)

    compiled = graph.compile(checkpointer=get_checkpointer())
    return compiled


def run_workflow(pr_url: str, repo_path: str = None) -> dict:
    graph = build_graph()
    thread_id = f"pr-review-{pr_url[-20:]}"
    initial_state = {"pr_url": pr_url, "repo_path": repo_path}
    result = _run_workflow("pr_review", graph, initial_state, thread_id)
    result["verdict"] = result.get("escalation_verdict", result.get("verdict"))
    result["review_summary"] = result.get("escalation_summary", result.get("review_summary"))
    return result
