"""WORKFLOW_NAME workflow nodes — thin wrappers around shared core nodes."""

from langgraph_maestro.nodes import (
    make_decompose_node,
    make_execute_node,
    make_review_node,
)
from langgraph_maestro.core.config import workflow_config_path
from pathlib import Path

_CONFIG = workflow_config_path(__file__)
_PROMPTS = str(Path(__file__).parent / "prompts")

decompose_node = make_decompose_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)

execute_node = make_execute_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)

review_node = make_review_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)

__all__ = ["decompose_node", "execute_node", "review_node"]
