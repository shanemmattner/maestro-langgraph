"""Default workflow package."""

from .graph import build_graph, run_workflow

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "default",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Configurable pipeline with optional critique, test_gen, and verify phases.",
)

__all__ = ["build_graph", "run_workflow"]
