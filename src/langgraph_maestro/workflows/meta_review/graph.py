"""Meta Review workflow graph."""
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph_maestro.workflows.meta_review.state import MetaReviewState
from langgraph_maestro.workflows.meta_review.nodes import load_run, analyze, critique, recommend, report
from langgraph_maestro.core.config import load_config, workflow_config_path


def build_graph() -> StateGraph:
    """Build the meta_review workflow graph."""
    graph = StateGraph(MetaReviewState)
    
    # Add nodes
    graph.add_node("load_run", load_run)
    graph.add_node("analyze", analyze)
    graph.add_node("critique", critique)
    graph.add_node("recommend", recommend)
    graph.add_node("report", report)
    
    # Define edges
    graph.set_entry_point("load_run")
    graph.add_edge("load_run", "analyze")
    graph.add_edge("analyze", "critique")
    graph.add_edge("critique", "recommend")
    graph.add_edge("recommend", "report")
    graph.add_edge("report", END)
    
    return graph.compile()


def run_workflow(
    trace_id: Optional[str] = None,
    log_file: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the meta_review workflow.
    
    Args:
        trace_id: Langfuse trace ID to analyze
        log_file: Path to JSONL log file to analyze
        config_path: Optional path to config file
    
    Returns:
        Final state with report
    """
    # Load config
    if config_path is None:
        config_path = workflow_config_path(__file__)
    config = load_config(config_path)
    
    # Initialize graph
    graph = build_graph()
    
    # Initial state
    initial_state = {
        "trace_id": trace_id,
        "log_file": log_file,
    }
    
    # Run the workflow
    result = graph.invoke(initial_state, config=config)
    
    return result
