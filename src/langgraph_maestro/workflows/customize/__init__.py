"""Customize workflow — multi-round LLM interview for workflow generation."""

from .graph import build_graph, run_workflow
from .nodes import (
    collect_answers_node,
    generate_node,
    interview_node,
    synthesize_node,
    validate_node,
    write_output_node,
)
from .schemas import (
    AnswerSynthesis,
    InterviewQuestions,
    WorkflowSpec,
)
from .state import CustomizeState

from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "customize",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="Multi-round LLM interview to generate a custom workflow.",
)

__all__ = [
    "CustomizeState",
    "AnswerSynthesis",
    "InterviewQuestions",
    "WorkflowSpec",
    "interview_node",
    "collect_answers_node",
    "synthesize_node",
    "generate_node",
    "validate_node",
    "write_output_node",
    "build_graph",
    "run_workflow",
]
