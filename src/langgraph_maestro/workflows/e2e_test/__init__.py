"""E2E Test workflow module."""

from .graph import run_workflow, build_graph
from .state import E2ETestState
from .nodes import (
    analyze_node,
    design_node,
    generate_node,
    execute_node,
    evaluate_node,
    report_node,
    should_retry,
)

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "e2e_test",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Generates and runs end-to-end tests with retry logic.",
)

__all__ = [
    "run_workflow",
    "build_graph",
    "E2ETestState",
    "analyze_node",
    "design_node",
    "generate_node",
    "execute_node",
    "evaluate_node",
    "report_node",
    "should_retry",
]
