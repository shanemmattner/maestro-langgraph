---
name: debug-workflow
description: Debug failing or misbehaving maestro workflows. Use when a workflow produces wrong results, hangs, or crashes.
---

# Debug Workflow

Use this skill when investigating workflow failures, unexpected behavior, or performance issues.

## 1. Check JSONL Logs

Maestro writes JSON-line logs via `langgraph_maestro.core.logging`. Each entry has `ts`, `level`, `logger`, `msg`, and optional `data` with structured extras.

```bash
# Find recent log files
ls -lt logs/

# Stream a log file with jq for readability
cat logs/maestro_*.jsonl | jq .

# Filter for errors
cat logs/maestro_*.jsonl | jq 'select(.level == "ERROR")'

# Filter by node name
cat logs/maestro_*.jsonl | jq 'select(.logger | contains("decompose"))'
```

Key log messages to look for:
- `decompose_start`, `execute_start`, `review_start` -- phase entry points
- `call_llm` with `error` in data -- LLM call failures
- `stall_detected` -- stall detector triggered
- `budget_exceeded` -- token budget exhausted

## 2. Check Langfuse Traces

If Langfuse is running (`http://localhost:3100`):
- Find the trace by workflow run ID or timestamp
- Check `gen_ai.request.model` to verify which model was actually used
- Check `gen_ai.usage.input_tokens` / `output_tokens` for unexpected token counts
- Check `gen_ai.input.messages` for the actual prompt sent (requires `MAESTRO_TRACE_CONTENT=true`)

## 3. Common Errors and Fixes

### "Config not found" / KeyError on config
- Verify `config.yaml` exists in the workflow directory
- Check `workflow_config_path(__file__)` is called from `graph.py`, not a subdirectory
- In tests, use `tmp_config` fixture and pass the path via `state["config_path"]`

### "Model fallback exhausted" / all models fail
- Check API keys: `ANTHROPIC_API_KEY`, `MINIMAX_API_KEY`
- Check model names in `config.yaml` match routing rules in `get_provider()`
- Test with `call_llm(prompt, model)` directly to isolate provider issues

### Stall detection triggers
- `StallDetector` fires on timeout, no-progress (same state after N iterations), or loop count exceeded
- Check `loops.max_review_rounds`, `loops.max_critique_rounds` in config.yaml
- Inspect state between iterations -- is the node actually modifying state?

### Graph hangs / never reaches END
- Check conditional edges -- missing return values route to wrong nodes
- Check for infinite loops between review and execute nodes
- Add `logger.info` at node entry/exit to trace the path

### Structured output parse failure
- `call_llm_structured()` retries on JSON parse errors (Instructor-style)
- Check the Pydantic schema matches what the LLM is actually returning
- Look for `json_parse_error` in JSONL logs

## 4. Test Individual Nodes

Isolate a single node to reproduce the issue:

```python
from langgraph_maestro.nodes import make_decompose_node

node = make_decompose_node(config_path, SchemaClass, prompts_dir)
result = node({"task": "test task", "cwd": "/tmp"})
print(result)
```

With mocking (in a test):

```python
def test_decompose_isolated(mock_llm, tmp_config):
    import json
    mock_llm.append({"content": json.dumps({"subtasks": [{"id": 1, "description": "do thing"}]}), "model": "mock", "latency": 0.1})
    config_path = tmp_config({"phases": {"decompose": ["mock-model"]}, "loops": {}})
    node = make_decompose_node(config_path, MySchema, str(prompts_dir))
    result = node({"task": "test", "config_path": config_path})
    assert "subtasks" in result
```

## 5. SQLite Checkpoint Inspection

Maestro uses SQLite-backed LangGraph checkpointing:

```python
from langgraph_maestro.core.checkpointer import get_checkpointer
cp = get_checkpointer()
# Inspect checkpoint state for a thread
```

## 6. Environment Checklist

- `ANTHROPIC_API_KEY` set and valid
- `MINIMAX_API_KEY` set (if using MiniMax models)
- `MAESTRO_TRACE_CONTENT=true` for full prompt/response in traces
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` set (if using Langfuse)
- Langfuse stack running: `docker compose up -d` in `infrastructure/`
