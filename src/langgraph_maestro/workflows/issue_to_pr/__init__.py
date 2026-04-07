"""Issue-to-PR workflow package."""

from .graph import build_graph, run_workflow

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "issue_to_pr",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Fetch GitHub issue → decompose → execute → review → PR.",
)

__all__ = ["build_graph", "run_workflow"]
