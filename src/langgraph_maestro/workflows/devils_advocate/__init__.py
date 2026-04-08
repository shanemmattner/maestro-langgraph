"""Devil's Advocate workflow — adversarial design review."""

from .graph import build_graph, run_workflow

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "devils_advocate",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Adversarial review that challenges a proposal with counter-evidence and alternatives.",
)

__all__ = ["build_graph", "run_workflow"]
