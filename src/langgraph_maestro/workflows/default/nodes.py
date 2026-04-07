"""Default workflow nodes — thin wrappers around shared core nodes.

This is the default workflow combining maestro and open_swe capabilities.
Use config to enable/disable critique, test_gen, and escalation phases.
"""

from langgraph_maestro.nodes import (
    make_decompose_node, make_execute_node, make_review_node,
    make_critique_node, make_test_gen_node, make_escalate_node,
    baseline_node,
)
from langgraph_maestro.core.schemas import DecomposeOutput
from langgraph_maestro.core.config import workflow_config_path
from pathlib import Path

_CONFIG = workflow_config_path(__file__)
_PROMPTS = str(Path(__file__).parent / "prompts")

# Create default-specific node instances using factories
decompose_node = make_decompose_node(
    config_path_default=_CONFIG,
    schema_class=DecomposeOutput,
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

critique_node = make_critique_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)

test_gen_node = make_test_gen_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)

escalate_node = make_escalate_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)

# Re-export baseline_node directly (no customization needed)
__all__ = [
    "baseline_node", "decompose_node", "execute_node", "review_node",
    "critique_node", "test_gen_node", "escalate_node",
]
