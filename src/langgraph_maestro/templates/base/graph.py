"""WORKFLOW_NAME workflow graph — decompose → execute → review pipeline."""

import logging
from pathlib import Path

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
from langgraph_maestro.core.config import load_config, workflow_config_path
from langgraph_maestro.core.runner import run_workflow as _run_workflow
from .state import WorkflowState
from .nodes import decompose_node, execute_node, review_node

logger = logging.getLogger(__name__)

_config = load_config(workflow_config_path(__file__))
_loops = _config.get("loops", {})


def route_review(state: WorkflowState) -> str:
    """Route after review: loop back to execute on REJECT, end otherwise."""
    verdict = state.get("verdict", "APPROVE")
    if verdict == "APPROVE" or verdict == "NITS":
        return END
    review_rounds = state.get("review_rounds", 0)
    max_rounds = state.get("max_review_rounds", _loops.get("max_review_rounds", 2))
    if review_rounds < max_rounds:
        return "execute"
    logger.warning("review_max_rounds_reached", extra={"rounds": review_rounds})
    return END


def build_graph(config_path: str = ""):
    """Build the WORKFLOW_NAME workflow graph.

    Returns compiled StateGraph with checkpointer.
    """
    if not config_path:
        config_path = workflow_config_path(__file__)

    graph = StateGraph(WorkflowState)

    graph.add_node("decompose", decompose_node)
    graph.add_node("execute", execute_node)
    graph.add_node("review", review_node)

    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "execute")
    graph.add_edge("execute", "review")
    graph.add_conditional_edges("review", route_review)

    compiled = graph.compile(checkpointer=get_checkpointer())
    return compiled


def run_workflow(
    task: str,
    config_path: str = "",
    cwd: str | None = None,
) -> dict:
    """Run the WORKFLOW_NAME workflow end-to-end."""
    if not config_path:
        config_path = workflow_config_path(__file__)

    graph = build_graph(config_path)
    initial_state = {
        "task": task,
        "config_path": config_path,
        "phase": "start",
        "errors": [],
    }
    if cwd:
        initial_state["cwd"] = cwd

    return _run_workflow("WORKFLOW_NAME", graph, initial_state)
