"""Adaptive workflow graph — 5-node MVP: think, plan, adversarial review, act+verify per piece, done.

Flow:
  START -> think -> plan -> adversarial_review ->
    route: approved -> act, not approved + budget -> plan, exhausted -> done
    act -> verify ->
    route: verified + more -> act, verified + done -> done,
           not verified + budget -> act, exhausted -> done
    done -> END
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
from langgraph_maestro.core.config import load_config, workflow_config_path
from langgraph_maestro.core.runner import run_workflow as _run_workflow
from .state import AdaptiveState
from .nodes import (
    think_node,
    plan_node,
    adversarial_review_node,
    act_node,
    verify_node,
    done_node,
)

logger = logging.getLogger(__name__)

# Load config at module level for route functions
_config = load_config(workflow_config_path(__file__))
_loops_config = _config.get("loops", {})


# ── Routing functions ────────────────────────────────────────────────────────


def route_after_review(state: AdaptiveState) -> str:
    """Route after adversarial review: approved -> act, rejected -> replan or done."""
    approved = state.get("plan_approved", False)
    if approved:
        return "act"

    replan_rounds = state.get("replan_rounds", 0)
    max_replan = _loops_config.get("max_replan_rounds", 2)
    if replan_rounds < max_replan:
        logger.info("replan", extra={"replan_rounds": replan_rounds})
        return "plan"

    logger.warning("replan_exhausted", extra={"replan_rounds": replan_rounds})
    return "done"


def route_after_verify(state: AdaptiveState) -> str:
    """Route after verify: next piece, retry, or done."""
    pieces = state.get("pieces", [])
    current_index = state.get("current_piece_index", 0)
    piece_retries = state.get("piece_retries", 0)
    max_retries = _loops_config.get("max_piece_retries", 2)

    # Check if the last verification passed (current_piece_index was advanced by verify_node)
    # If current_index was advanced, the previous piece was verified
    piece_results = state.get("piece_results", [])
    last_result = piece_results[-1] if piece_results else {}
    verified = last_result.get("verified", False)

    if verified:
        # Check if there are more pieces
        if current_index < len(pieces):
            return "act"
        return "done"

    # Not verified — retry or give up
    if piece_retries < max_retries:
        logger.info("piece_retry", extra={"index": current_index, "retries": piece_retries})
        return "act"

    logger.warning("piece_retries_exhausted", extra={"index": current_index, "retries": piece_retries})
    return "done"


# ── Graph construction ───────────────────────────────────────────────────────


def build_graph(config_path: str = workflow_config_path(__file__)):
    """Build the adaptive workflow graph.

    Flow: think -> plan -> adversarial_review -> [act -> verify per piece] -> done -> END

    Returns compiled StateGraph with checkpointer.
    """
    logger.info("adaptive_graph_compile_start")

    graph = StateGraph(AdaptiveState)

    # ── Add all nodes ──
    graph.add_node("think", think_node)
    graph.add_node("plan", plan_node)
    graph.add_node("adversarial_review", adversarial_review_node)
    graph.add_node("act", act_node)
    graph.add_node("verify", verify_node)
    graph.add_node("done", done_node)

    # ── Entry point ──
    graph.set_entry_point("think")

    # ── Static edges ──
    graph.add_edge("think", "plan")
    graph.add_edge("plan", "adversarial_review")
    graph.add_edge("act", "verify")
    graph.add_edge("done", END)

    # ── Conditional edges ──
    graph.add_conditional_edges("adversarial_review", route_after_review)
    graph.add_conditional_edges("verify", route_after_verify)

    compiled = graph.compile(checkpointer=get_checkpointer())
    logger.info("adaptive_graph_compile_done")
    return compiled


def run_workflow(
    task: str,
    config_path: str = workflow_config_path(__file__),
    cwd: str | None = None,
) -> dict:
    """Run the adaptive workflow end-to-end.

    Args:
        task: The task/problem description.
        config_path: Path to the workflow config YAML.
        cwd: Working directory for code operations.

    Returns:
        Final state dict with summary and piece results.
    """
    graph = build_graph(config_path)
    initial_state = {"task": task, "config_path": config_path}
    if cwd:
        initial_state["cwd"] = cwd
    thread_id = f"adaptive-{hash(task) & 0xFFFFFFFF:08x}"
    return _run_workflow("adaptive", graph, initial_state, thread_id)
