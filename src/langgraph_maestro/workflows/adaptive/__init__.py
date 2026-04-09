"""Adaptive workflow package."""

from .graph import build_graph, run_workflow

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "adaptive",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="MVP adaptive loop: think, plan, adversarial review, act+verify per piece.",
)

__all__ = ["build_graph", "run_workflow"]
