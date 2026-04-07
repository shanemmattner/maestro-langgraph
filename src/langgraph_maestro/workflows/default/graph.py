"""Default workflow graph — config-driven conditional wiring.

Combines maestro (baseline → decompose → validate → execute → review) with
optional phases: critique, test_gen, escalate (from open_swe).

Enable optional phases via config.yaml:
  - phases.critique.enabled: true → adds critique node between validate and execute
  - phases.test_gen.enabled: true → adds test_gen node between critique and execute
  - phases.escalate.enabled: true → allows escalation from review

Flow (with all phases enabled):
  START → baseline → decompose → validate → critique ⇄ decompose →
         test_gen → execute → review ⇄ execute/decompose/escalate → END
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph_maestro.core.checkpointer import get_checkpointer
from langgraph_maestro.core.config import load_config, workflow_config_path
from langgraph_maestro.core.runner import run_workflow as _run_workflow
from langgraph_maestro.core.validation import validate_subtasks
from .state import MaestroState
from .nodes import (
    baseline_node, decompose_node, execute_node, review_node,
    critique_node, test_gen_node, escalate_node,
)

logger = logging.getLogger(__name__)

# Load config at module level for route functions
_config = load_config(workflow_config_path(__file__))
_loops_config = _config.get("loops", {})
_escalation_config = _config.get("escalation", {})


def validate_subtasks_node(state: MaestroState) -> dict:
    """Validate subtasks before execution - quality gate."""
    subtasks = state.get("subtasks", [])
    result = validate_subtasks(subtasks)
    # Return warnings as list of strings for state
    warning_messages = [w["message"] for w in result["warnings"]]
    return {
        "subtask_warnings": warning_messages,
        "phase": result["phase"],
    }


def route_critique(state: MaestroState) -> str:
    """Route after critique: back to decompose if rejected, forward if approved."""
    if state.get("plan_approved", True):
        return "test_gen" if _config.get("phases", {}).get("test_gen", {}).get("enabled", False) else "execute"
    critique_rounds = state.get("critique_rounds", 0)
    max_rounds = state.get("max_critique_rounds", 1)
    if critique_rounds >= max_rounds:
        logger.warning("critique_max_rounds_reached", extra={"rounds": critique_rounds})
        return "test_gen" if _config.get("phases", {}).get("test_gen", {}).get("enabled", False) else "execute"
    return "decompose"


def route_review(state: MaestroState) -> str:
    """Route after review: retry, re-plan, escalate, or end."""
    verdict = state.get("verdict", "APPROVE")
    if verdict in ("APPROVE", "NITS"):
        return END

    review_rounds = state.get("review_rounds", 0)
    max_review_rounds = state.get("max_review_rounds", 2)
    replan_rounds = state.get("replan_rounds", 0)
    max_replan = _loops_config.get("max_replan_rounds", 1)

    # Classify issue type from review
    issues = state.get("review_issues", [])
    issue_types = {i.get("issue_type", "implementation") for i in issues}

    # Escalate on low confidence / unclear
    escalation_enabled = _escalation_config.get("enabled", False)
    if escalation_enabled and "unclear" in issue_types:
        return "escalate"

    # Re-plan if plan issues and budget remains
    if "plan" in issue_types and replan_rounds < max_replan:
        return "decompose"

    # Retry implementation if budget remains
    if review_rounds < max_review_rounds:
        return "execute"

    logger.warning("review_max_rounds_reached", extra={"rounds": review_rounds})
    return END


def build_graph(config_path: str = workflow_config_path(__file__)):
    """Build the default workflow graph with config-driven phase wiring.

    Flow: baseline → decompose → validate → [critique →] [test_gen →] execute → review ⇄ execute/decompose/escalate → END

    Returns compiled StateGraph with checkpointer.
    """
    logger.info("graph_compile_start")

    config = load_config(config_path)

    # Read loop limits from config
    loops = config.get("loops", {})

    # Read phase config for conditional wiring
    phases = config.get("phases", {})
    critique_enabled = phases.get("critique", {}).get("enabled", False)
    test_gen_enabled = phases.get("test_gen", {}).get("enabled", False)
    escalate_enabled = phases.get("escalate", {}).get("enabled", False)

    graph = StateGraph(MaestroState)

    # Add nodes (all nodes always added, but conditionally wired)
    graph.add_node("baseline_check", baseline_node)
    graph.add_node("decompose", decompose_node)
    graph.add_node("validate_subtasks", validate_subtasks_node)
    graph.add_node("execute", execute_node)
    graph.add_node("review", review_node)

    # Add optional nodes
    if critique_enabled:
        graph.add_node("critique", critique_node)
    if test_gen_enabled:
        graph.add_node("test_gen", test_gen_node)
    if escalate_enabled:
        graph.add_node("escalate", escalate_node)

    # Entry: baseline → decompose → validate
    graph.set_entry_point("baseline_check")
    graph.add_edge("baseline_check", "decompose")
    graph.add_edge("decompose", "validate_subtasks")

    # validate → (critique or execute)
    if critique_enabled:
        graph.add_edge("validate_subtasks", "critique")
        # critique → (test_gen or execute or decompose)
        graph.add_conditional_edges("critique", route_critique)

        # test_gen → execute (if enabled)
        if test_gen_enabled:
            graph.add_edge("test_gen", "execute")
        # else: execute is already the fallback from route_critique
    else:
        graph.add_edge("validate_subtasks", "execute")

    # execute → review
    graph.add_edge("execute", "review")

    # Review → END (approve/nits) or → execute/decompose/escalate (reject)
    graph.add_conditional_edges("review", route_review)

    # Escalate → END (if enabled)
    if escalate_enabled:
        graph.add_edge("escalate", END)

    compiled = graph.compile(checkpointer=get_checkpointer())
    logger.info("graph_compile_done")
    return compiled


def run_workflow(
    task: str,
    config_path: str = workflow_config_path(__file__),
    cwd: str | None = None,
) -> dict:
    """Run the default workflow end-to-end.

    Args:
        task: The task/problem description.
        config_path: Path to the workflow config YAML.
        cwd: Working directory for code operations.

    Returns:
        Final state dict with verdict, subtasks, and execution log.
    """
    graph = build_graph(config_path)
    initial_state = {"task": task, "config_path": config_path}
    if cwd:
        initial_state["cwd"] = cwd
    thread_id = f"default-{hash(task) & 0xFFFFFFFF:08x}"
    return _run_workflow("default", graph, initial_state, thread_id)
