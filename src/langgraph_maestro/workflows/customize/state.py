"""Customize workflow state definition."""
from typing import TypedDict, Optional
from langgraph_maestro.core.state import BaseWorkflowState


class CustomizeState(BaseWorkflowState):
    """State for the customize workflow."""
    
    # Input
    user_request: str
    
    # Survey phase output
    available_workflows: list[dict]  # List of {name, description, config}
    
    # Match phase output
    matched_workflow: Optional[dict]  # {name, description, confidence}
    match_reasoning: Optional[str]
    
    # Spec phase output
    customization_spec: Optional[dict]  # {phases, nodes, config_patches}
    
    # Output phase
    final_report: Optional[str]
