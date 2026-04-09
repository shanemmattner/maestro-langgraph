"""Default workflow package."""

from .graph import build_graph, run_workflow

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "default",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Full 11-node pipeline: analyze, research, context engineering, per-piece execution, adversarial review, verification, and after-action review.",
)

__all__ = ["build_graph", "run_workflow"]
