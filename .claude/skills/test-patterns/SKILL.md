---
name: test-patterns
description: Testing guide for langgraph-maestro. Use when writing or debugging tests for nodes, workflows, or LLM integrations.
---

# Test Patterns

Use this skill when writing tests for maestro components. Tests live in `tests/` and use pytest.

## Running Tests

```bash
uv run pytest                          # All tests
uv run pytest tests/test_decompose.py  # Single file
uv run pytest -k "test_review"         # By name pattern
uv run pytest -x                       # Stop on first failure
```

## Core Fixtures (from `tests/conftest.py`)

### `mock_llm` -- Mock All LLM Providers

Patches `_providers` dict to replace all registered providers with a mock function. Yields a list you append responses to:

```python
def test_my_node(mock_llm):
    # Queue responses (popped in order)
    mock_llm.append({"content": "response text", "model": "mock", "latency": 0.1})
    # ... call code that uses call_llm() ...
    # If list is empty, returns default: {"content": "mock response", "model": model, "latency": 0.1}
```

### `mock_llm_json` -- Mock with JSON Responses

Wraps `mock_llm` for structured output testing:

```python
def test_structured(mock_llm_json):
    mock_llm_json({"subtasks": [{"id": 1, "description": "do thing"}]})
    # ... call code that uses call_llm_structured() ...
```

### `tmp_config` -- Temporary Config Files

Creates a temporary `config.yaml` and clears the config cache:

```python
def test_with_config(tmp_config):
    config_path = tmp_config({
        "phases": {"decompose": ["mock-model"], "execute": ["mock-model"]},
        "loops": {"max_review_rounds": 1},
    })
    # Pass config_path into nodes or state
```

### `disable_pe` -- Auto-disabled Prompt Engineering

Applied automatically to all tests. Patches `improve_prompt` to pass through unchanged. To test PE itself, mark the test:

```python
@pytest.mark.enable_pe
def test_prompt_improvement():
    ...
```

### `setup_test_logging` -- Capture JSONL Logs

Configures logging to write to `tmp_path` for inspection:

```python
def test_logging(setup_test_logging):
    log_file = setup_test_logging
    # ... run code ...
    # Read log_file to verify log entries
```

## Testing Nodes in Isolation

Nodes are closures returned by factories. Test them by calling directly with a mock state dict:

```python
def test_decompose_node(mock_llm, tmp_config):
    import json
    mock_llm.append({
        "content": json.dumps({"subtasks": [{"id": 1, "description": "step one"}]}),
        "model": "mock",
        "latency": 0.1,
    })
    config_path = tmp_config({"phases": {"decompose": ["mock-model"]}, "loops": {}})
    node = make_decompose_node(config_path, MySchema, str(prompts_dir))
    result = node({"task": "implement feature", "config_path": config_path})
    assert "subtasks" in result
```

## Testing Graph Routing

Compile the graph and invoke with mock state to verify edge routing:

```python
def test_graph_routes_to_end(mock_llm, tmp_config):
    # Queue enough responses for all nodes in the path
    for _ in range(3):
        mock_llm.append({"content": "ok", "model": "mock", "latency": 0.1})

    config_path = tmp_config({...})
    result = graph.invoke({"task": "test", "config_path": config_path, "cwd": "/tmp"})
    assert result.get("result") is not None
```

## Testing Conditional Edges

Test the routing function directly:

```python
def test_review_routes_to_execute_on_reject():
    state = {"review_verdict": "reject", "review_round": 1}
    assert review_router(state) == "execute"

def test_review_routes_to_end_on_accept():
    state = {"review_verdict": "accept"}
    assert review_router(state) == END
```

## Mocking MC Agent Calls

For nodes that use `run_mc_agent()`:

```python
from unittest.mock import patch

def test_execute_with_mc(mock_llm, tmp_config):
    with patch("langgraph_maestro.core.mc.run_mc_agent", return_value=0):
        node = make_execute_node(config_path, prompts_dir)
        result = node({"task": "fix bug", "cwd": "/tmp", "config_path": config_path})
```

## Common Pitfalls

- **Config cache** -- `load_config()` caches results. Always use `tmp_config` (which calls `clear_cache()`) or call `clear_cache()` manually.
- **Not enough mock responses** -- if a workflow calls `call_llm` 3 times, queue 3 responses. Exhausted list returns a default.
- **PE consuming mock responses** -- `disable_pe` is autouse, but if you mark `@pytest.mark.enable_pe`, PE will pop from `mock_llm` too.
- **State key names** -- node tests fail silently if state keys don't match what the node reads. Check the node source for expected keys.
- **Structured output tests** -- `call_llm_structured` retries on parse failure. Queue valid JSON or expect multiple mock pops.
