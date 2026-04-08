"""Meta Review workflow."""
from langgraph_maestro.workflows.meta_review.graph import build_graph, run_workflow
from langgraph_maestro.workflows.meta_review.state import MetaReviewState

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "meta_review",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Analyzes a completed workflow run and produces a quality meta-review.",
)

__all__ = ["build_graph", "run_workflow", "MetaReviewState"]
