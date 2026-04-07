"""State for the chain_of_thought workflow."""
from typing import Any, Dict, List
from typing_extensions import TypedDict

from langgraph_maestro.core.state import BaseWorkflowState


class ChainOfThoughtState(BaseWorkflowState):
    # Inputs
    question: str
    context: str            # optional background context
    domain: str             # "math", "logic", "science", "business", "general"

    # Decomposition
    sub_questions: List[str]
    assumptions: List[str]

    # Step-by-step reasoning
    reasoning_steps: List[Dict[str, Any]]   # [{step_num, question, reasoning, conclusion}]
    step_errors: List[str]                  # any detected errors in reasoning

    # Final answer
    answer: str
    confidence: float
    key_assumptions: List[str]
    caveats: List[str]
    verdict: str            # "ANSWERED" | "PARTIAL" | "CANNOT_ANSWER"
