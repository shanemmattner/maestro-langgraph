"""Chain-of-thought workflow — decompose → reason step-by-step → synthesize answer."""
from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.workflows.chain_of_thought.graph import build_graph, run_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "chain_of_thought",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Structured step-by-step reasoning: decompose question → reason each step → synthesize.",
)

__all__ = ["build_graph", "run_workflow"]
