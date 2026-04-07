"""Meta Review workflow state."""
from typing import Optional, Any, List, Dict
from langgraph_maestro.core.state import BaseWorkflowState


class MetaReviewState(BaseWorkflowState):
    """State for the meta_review workflow."""
    
    # Input
    trace_id: Optional[str] = None
    log_file: Optional[str] = None
    run_data: Optional[Dict[str, Any]] = None
    
    # Analysis phase outputs
    summary: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    
    # Critique phase outputs  
    critique: Optional[str] = None
    issues: Optional[List[str]] = None
    
    # Recommend phase outputs
    recommendations: Optional[List[str]] = None
    priority: Optional[str] = None
    
    # Report phase outputs
    report: Optional[str] = None
