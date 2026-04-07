"""E2E Test workflow graph definition with retry logic."""

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from langgraph_maestro.core.runner import run_workflow as run_workflow_base
from langgraph_maestro.core.state import BaseWorkflowState
from .state import E2ETestState
from langgraph_maestro.core.config import workflow_config_path
from .nodes import (
    analyze_node,
    design_node,
    generate_node,
    execute_node,
    evaluate_node,
    report_node,
    should_retry,
)

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """Build the E2E Test workflow graph.
    
    Flow: analyze -> design -> generate -> execute -> evaluate -> report
                    ^                                        |
                    |_________ (retry if failed) __________|
    """
    graph = StateGraph(E2ETestState)
    
    # Add nodes
    graph.add_node("analyze", analyze_node)
    graph.add_node("design", design_node)
    graph.add_node("generate", generate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("report", report_node)
    
    # Define edges
    graph.add_edge("__start__", "analyze")
    graph.add_edge("analyze", "design")
    graph.add_edge("design", "generate")
    graph.add_edge("generate", "execute")
    graph.add_edge("execute", "evaluate")
    
    # Conditional edge: evaluate -> (report or generate) based on should_retry
    graph.add_conditional_edges(
        "evaluate",
        should_retry,
        {
            True: "generate",  # Retry: go back to generate
            False: "report",   # Pass or max retries: go to report
        }
    )
    
    graph.add_edge("report", END)
    
    return graph


def run_workflow(
    diff_file: str,
    pr_number: str,
    cwd: str,
    config_path: str = workflow_config_path(__file__),
    thread_id: str = "e2e-test",
    commit_tests: bool = False,
) -> dict:
    """Run the E2E Test workflow.
    
    Args:
        diff_file: Path to diff file or PR diff content
        pr_number: PR number
        cwd: Working directory
        config_path: Path to config file
        thread_id: Thread ID for checkpointing
        commit_tests: Whether to commit generated tests
    
    Returns:
        Final state dict with test results and report
    """
    logger.info("e2e_test_workflow_start", extra={"pr_number": pr_number, "cwd": cwd})
    
    # Load config for max_retries
    from langgraph_maestro.core.config import load_config
    config = load_config(config_path)
    max_retries = config.get("max_retries", 3)
    
    # Build the graph
    graph = build_graph()
    compiled = graph.compile()
    
    # Initial state
    initial_state: E2ETestState = {
        "diff_file": diff_file,
        "pr_number": pr_number,
        "cwd": cwd,
        "config_path": config_path,
        "retry_count": 0,
        "max_retries": max_retries,
    }
    
    # Run the workflow
    result = run_workflow_base(
        name="e2e_test",
        graph=compiled,
        initial_state=initial_state,
        thread_id=thread_id,
    )
    
    logger.info("e2e_test_workflow_done", extra={
        "pr_number": pr_number,
        "verdict": result.get("verdict", "UNKNOWN"),
        "retry_count": result.get("retry_count", 0),
    })
    
    return result
