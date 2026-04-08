---
name: add-node
description: Create a new reusable node factory for LangGraph workflows. Use when adding a new processing step that multiple workflows can share.
---

# Add Node

Use this skill when creating a new reusable graph node (a function that transforms workflow state).

## Factory Pattern

All shared nodes follow the `make_X_node()` factory pattern. The factory accepts configuration and returns a closure that takes `state: dict` and returns a partial state update.

```python
# src/langgraph_maestro/nodes/my_node.py

import logging
import time
from pathlib import Path
from typing import Any, Callable, Type

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_my_node(
    config_path_default: str,
    prompts_dir: str,
    schema_class: Type[Any] | None = None,
) -> Callable[[dict], dict]:
    """Create a my_node with the given configuration.

    Args:
        config_path_default: Path to workflow config.yaml
        prompts_dir: Path to prompts/ directory
        schema_class: Optional Pydantic model for structured output
    """
    prompts_path = Path(prompts_dir)

    def my_node(state: dict) -> dict:
        start = time.time()
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("my_phase", config)

        template = _load_prompt("my_prompt", prompts_path)
        prompt = template.replace("{task}", state.get("task", ""))

        result = call_llm_with_fallback(prompt, models, phase="my_phase", config=config)

        logger.info("my_node_done", extra={"latency": round(time.time() - start, 3)})
        return {"my_output": result["content"]}

    return my_node
```

## Step by Step

1. **Create the file** at `src/langgraph_maestro/nodes/my_node.py`.

2. **Write the factory** -- `make_my_node()` returns a closure. The factory binds config/prompts; the closure receives graph state.

3. **Use `call_llm_with_fallback()`** for LLM calls -- it tries models in preference order from config. Use `call_llm_structured()` if you need Pydantic validation on the response.

4. **Load prompts from files** -- use `_load_prompt()` reading from the workflow's `prompts/` directory. Never hardcode prompts.

5. **Export from `nodes/__init__.py`**:
   ```python
   from langgraph_maestro.nodes.my_node import make_my_node
   ```
   Add to `__all__`.

6. **Wire into a workflow** in the workflow's `nodes.py`:
   ```python
   from langgraph_maestro.nodes import make_my_node
   my_node = make_my_node(config_path, prompts_dir)
   ```

7. **Write tests** -- test the node in isolation using `mock_llm` and `tmp_config` fixtures.

## Existing Node Factories

| Factory | Purpose |
|---------|---------|
| `make_decompose_node` | Break task into subtasks |
| `make_execute_node` | Execute a subtask via MC agent |
| `make_review_node` | Review execution results |
| `make_critique_node` | Critique the decomposition plan |
| `make_test_gen_node` | Generate tests for implemented code |
| `make_escalate_node` | Escalate when confidence is low |
| `make_fetch_issue_node` | Fetch GitHub/GitLab issue details |
| `make_commit_pr_node` | Commit changes and open a PR |
| `make_reviewer_node` | Single reviewer in fan-out pattern |
| `make_synthesize_node` | Merge multiple reviewer outputs |
| `baseline_node` | Special: not a factory, direct function |

## Common Pitfalls

- **Returning wrong keys** -- the dict returned by the node must match keys in the workflow's `state.py` TypedDict.
- **Not using `call_llm_with_fallback`** -- using `call_llm` directly skips model fallback; prefer the fallback variant.
- **Forgetting PE integration** -- check `config.get("prompt_engineering", {})` if the node should support prompt improvement.
- **Hardcoded config path** -- always read `state.get("config_path", config_path_default)` so tests can override.
- **Missing `__init__.py` export** -- node won't be importable from `langgraph_maestro.nodes`.
