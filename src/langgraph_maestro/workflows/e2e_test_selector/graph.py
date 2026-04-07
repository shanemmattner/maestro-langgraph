"""E2E test selector — LangGraph workflow graph definition."""

import logging
from typing import Any

from langgraph.graph import StateGraph, END

from langgraph_maestro.core.runner import run_workflow as run_workflow_base
from .state import E2ETestSelectorState
from langgraph_maestro.core.config import workflow_config_path
from .nodes import (
    analyze_pr_node,
    discover_tests_node,
    select_tests_node,
    run_tests_node,
    report_node,
    publish_node,
)

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """Build the E2E test selector workflow.

    Flow: analyze_pr → discover_tests → select_tests → run_tests → report → END
    """
    graph = StateGraph(E2ETestSelectorState)

    graph.add_node("analyze_pr", analyze_pr_node)
    graph.add_node("discover_tests", discover_tests_node)
    graph.add_node("select_tests", select_tests_node)
    graph.add_node("run_tests", run_tests_node)
    graph.add_node("report", report_node)
    graph.add_node("publish", publish_node)

    graph.add_edge("__start__", "analyze_pr")
    graph.add_edge("analyze_pr", "discover_tests")
    graph.add_edge("discover_tests", "select_tests")
    graph.add_edge("select_tests", "run_tests")
    graph.add_edge("run_tests", "report")
    graph.add_edge("report", "publish")
    graph.add_edge("publish", END)

    return graph


def run_workflow(
    pr_diff: str,
    pr_number: str,
    repo_path: str,
    pr_url: str = "",
    config_path: str = workflow_config_path(__file__),
    thread_id: str = "e2e-test-selector",
) -> dict[str, Any]:
    """Run the E2E test selector workflow.

    Args:
        pr_diff: The PR diff content.
        pr_number: PR number.
        repo_path: Path to the repo under test.
        pr_url: Full GitHub PR URL (for commenting).
        config_path: Path to config YAML.
        thread_id: Thread ID for checkpointing.

    Returns:
        Final state with test results and report.
    """
    logger.info("e2e_selector_start", extra={"pr_number": pr_number, "repo_path": repo_path})

    graph = build_graph()
    compiled = graph.compile()

    initial_state: E2ETestSelectorState = {
        "pr_diff": pr_diff,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "repo_path": repo_path,
        "config_path": config_path,
    }

    result = run_workflow_base(
        name="e2e_test_selector",
        graph=compiled,
        initial_state=initial_state,
        thread_id=thread_id,
    )

    logger.info("e2e_selector_done", extra={
        "pr_number": pr_number,
        "overall_passed": result.get("overall_passed"),
        "tests_run": len(result.get("test_results", [])),
    })

    return result
