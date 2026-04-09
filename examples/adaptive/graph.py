"""Adaptive workflow graph — 5-node MVP: think, plan, adversarial review, act+verify per piece, done."""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
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

MAX_REPLAN_ROUNDS = 2
MAX_PIECE_RETRIES = 2


def route_after_review(state: AdaptiveState) -> str:
    approved = state.get("plan_approved", False)
    if approved:
        return "act"
    replan_rounds = state.get("replan_rounds", 0)
    if replan_rounds < MAX_REPLAN_ROUNDS:
        return "plan"
    return "done"


def route_after_verify(state: AdaptiveState) -> str:
    pieces = state.get("pieces", [])
    current_index = state.get("current_piece_index", 0)
    piece_retries = state.get("piece_retries", 0)
    piece_results = state.get("piece_results", [])
    last_result = piece_results[-1] if piece_results else {}
    verified = last_result.get("verified", False)

    if verified:
        if current_index < len(pieces):
            return "act"
        return "done"
    if piece_retries < MAX_PIECE_RETRIES:
        return "act"
    return "done"


def build_graph():
    """Build the adaptive workflow graph."""
    graph = StateGraph(AdaptiveState)

    graph.add_node("think", think_node)
    graph.add_node("plan", plan_node)
    graph.add_node("adversarial_review", adversarial_review_node)
    graph.add_node("act", act_node)
    graph.add_node("verify", verify_node)
    graph.add_node("done", done_node)

    graph.set_entry_point("think")
    graph.add_edge("think", "plan")
    graph.add_edge("plan", "adversarial_review")
    graph.add_edge("act", "verify")
    graph.add_edge("done", END)

    graph.add_conditional_edges("adversarial_review", route_after_review)
    graph.add_conditional_edges("verify", route_after_verify)

    compiled = graph.compile(checkpointer=get_checkpointer())
    return compiled


def run_workflow(task: str, cwd: str | None = None) -> dict:
    graph = build_graph()
    initial_state = {"task": task}
    if cwd:
        initial_state["cwd"] = cwd
    thread_id = f"adaptive-{hash(task) & 0xFFFFFFFF:08x}"
    return _run_workflow("adaptive", graph, initial_state, thread_id)
