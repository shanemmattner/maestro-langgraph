"""Customize workflow graph."""
from typing import Any

from langgraph.graph import StateGraph, END

from .state import CustomizeState
from .nodes import survey_node, match_node, spec_node, output_node


def build_graph() -> StateGraph:
    """Build the customize workflow graph."""
    graph = StateGraph(CustomizeState)
    
    # Add nodes
    graph.add_node("survey", survey_node)
    graph.add_node("match", match_node)
    graph.add_node("spec", spec_node)
    graph.add_node("output", output_node)
    
    # Define edges
    graph.set_entry_point("survey")
    graph.add_edge("survey", "match")
    graph.add_edge("match", "spec")
    graph.add_edge("spec", "output")
    graph.add_edge("output", END)
    
    return graph.compile()


async def run_workflow(user_request: str) -> dict[str, Any]:
    """Run the customize workflow."""
    graph = build_graph()
    
    initial_state: CustomizeState = {
        "user_request": user_request,
        "available_workflows": [],
        "matched_workflow": None,
        "match_reasoning": None,
        "customization_spec": None,
        "final_report": None,
    }
    
    result = await graph.ainvoke(initial_state)
    return result
