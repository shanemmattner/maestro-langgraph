"""E2E test selector workflow.

Analyzes a PR diff, discovers available E2E tests, uses an LLM to select
relevant tests, fans out execution, and collects results.
"""

from .graph import build_graph, run_workflow
from .state import E2ETestSelectorState

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "e2e_test_selector",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Selects and runs relevant E2E tests for a PR diff.",
)

__all__ = ["build_graph", "run_workflow", "E2ETestSelectorState"]
