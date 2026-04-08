---
name: add-workflow
description: Create a new LangGraph workflow from scratch. Use when adding a new orchestration pattern to the maestro framework.
---

# Add Workflow

Use this skill when creating a new workflow (a complete LangGraph state graph with config, nodes, and prompts).

## Quickest Path: Scaffold

```bash
uv run maestro init my_workflow --description "One-line summary"
```

This calls `langgraph_maestro.templates.scaffold_workflow()` which copies base templates into `src/langgraph_maestro/workflows/my_workflow/` with token replacement.

## Manual Workflow Structure

Every workflow lives in `src/langgraph_maestro/workflows/<name>/` and requires:

```
src/langgraph_maestro/workflows/my_workflow/
  __init__.py          # Empty or re-exports
  config.yaml          # Phase models, loop limits, feature flags
  graph.py             # StateGraph definition + run_workflow()
  state.py             # TypedDict for graph state
  nodes.py             # Workflow-specific node wrappers (call make_X_node factories)
  prompts/             # .txt prompt templates loaded by nodes
    decomposer.txt
    reviewer.txt
```

## Step by Step

1. **Define state** in `state.py` -- a `TypedDict` with at minimum `task`, `cwd`, `subtasks`, `result`.

2. **Write config.yaml** -- list models per phase in preference order. Use `enabled: false` for optional phases:
   ```yaml
   workflow: my_workflow
   phases:
     my_phase:
       - MiniMax-M2.5-highspeed
   loops:
     max_review_rounds: 2
   ```

3. **Build graph** in `graph.py`:
   ```python
   from langgraph.graph import StateGraph, END
   from langgraph_maestro.core.config import load_config, workflow_config_path

   config = load_config(workflow_config_path(__file__))
   # ... add nodes, edges, conditionals
   graph = builder.compile()

   def run_workflow(task: str, **kwargs) -> dict:
       return graph.invoke({"task": task, **kwargs})
   ```

4. **Create nodes** in `nodes.py` -- import factory functions from `langgraph_maestro.nodes` and bind config:
   ```python
   from langgraph_maestro.nodes import make_decompose_node
   decompose_node = make_decompose_node(config_path, SchemaClass, prompts_dir)
   ```

5. **Register** in `src/langgraph_maestro/workflows/__init__.py`:
   ```python
   from langgraph_maestro.workflows.my_workflow.graph import run_workflow as run_my_workflow
   ```
   Add `run_my_workflow` to `__all__`.

6. **Write tests** -- see `test-patterns` skill. At minimum test the graph compiles and runs with `mock_llm`.

## Key Imports

- `load_config`, `workflow_config_path`, `get_models_for_phase` from `langgraph_maestro.core.config`
- `call_llm`, `call_llm_with_fallback` from `langgraph_maestro.core.llm`
- `call_llm_structured` from `langgraph_maestro.core.structured`
- `get_checkpointer` from `langgraph_maestro.core.checkpointer`
- Node factories from `langgraph_maestro.nodes`

## Common Pitfalls

- **Forgot `workflow_config_path(__file__)`** -- config path must be relative to the graph.py file, not CWD.
- **Forgot registration** -- workflow won't appear in `maestro list` without the `workflows/__init__.py` import.
- **State key mismatch** -- node return dicts must use keys matching the TypedDict in state.py.
- **Missing prompts dir** -- `_load_prompt()` raises FileNotFoundError if prompts/ directory is absent.
- **Config not cleared in tests** -- always use the `tmp_config` fixture or call `clear_cache()` after changing configs.

## Reference Workflows

- `workflows/default/` -- full-featured with optional phases and conditional routing
- `workflows/chain_of_thought/` -- simpler linear flow
- `workflows/pr_review/` -- fan-out parallel pattern
