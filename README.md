# langgraph-maestro

Multi-agent LLM workflow orchestration framework built on [LangGraph](https://github.com/langchain-ai/langgraph).

## Features

- **Multi-provider LLM routing** -- call Claude, MiniMax, OpenRouter, or local MLX models through a unified `call_llm()` interface with automatic fallback
- **MC agent** -- run Claude Code as a programmable API with 84% fewer tool-schema tokens via lightweight MCP tool schemas
- **Durable checkpointing** -- SQLite-backed LangGraph checkpointing for pause/resume and crash recovery
- **OpenTelemetry tracing** -- GenAI semantic conventions (`gen_ai.*` attributes) with Langfuse integration for full prompt/response replay
- **Config-driven workflows** -- YAML files define phases, models, loop limits, and optional stages per workflow
- **Stall and budget detection** -- automatic timeout, no-progress, and loop detection; per-run and daily token budget guards
- **Structured output** -- Pydantic schema validation with auto-retry on parse failures (Instructor-style)
- **Prompt engineering** -- built-in prompt improvement node for automatic prompt refinement
- **9 built-in workflows** -- from simple chain-of-thought to full issue-to-PR automation

## Quick start

```bash
# Install
uv add langgraph-maestro

# List available workflows
uv run maestro list

# Run the default workflow
uv run maestro run default --task "Fix the login bug" --cwd ./my-repo

# Run a specific workflow
uv run maestro run issue_to_pr --task "Implement feature #42" --cwd ./my-repo
```

### Environment variables

```bash
ANTHROPIC_API_KEY=sk-...          # Required for Claude-based providers
MINIMAX_API_KEY=...               # Required for MiniMax models
MAESTRO_TRACE_CONTENT=true        # Include prompt/response in OTel spans (default: true)
LANGFUSE_PUBLIC_KEY=...           # Langfuse project key (optional)
LANGFUSE_SECRET_KEY=...           # Langfuse secret key (optional)
```

## Architecture

```
src/langgraph_maestro/
  core/           # Foundation: LLM calls, config, tracing, stall detection, budget
  nodes/          # Reusable graph nodes: decompose, execute, review, commit, etc.
  workflows/      # Complete workflow graphs, each with config.yaml + graph.py + state.py
```

**core/** provides the building blocks -- `call_llm()` for provider-routed LLM calls, `StallDetector` for timeout/loop detection, `load_config()` for YAML parsing, OTel tracing via `get_tracer()`, and structured output via `call_llm_structured()`.

**nodes/** contains reusable LangGraph nodes (decompose, execute, review, critique, test_gen, commit_pr, etc.) that workflows compose into graphs.

**workflows/** holds self-contained workflow packages. Each workflow directory contains a `config.yaml` (phase models, loop limits, feature flags), `graph.py` (LangGraph `StateGraph` definition), `state.py` (TypedDict state schema), and optionally custom nodes and prompts.

## Available workflows

| Workflow | Description |
|----------|-------------|
| `default` | Decompose, execute, review with optional critique/test_gen/escalation phases |
| `chain_of_thought` | Decompose, reason, synthesize -- for analytical tasks |
| `customize` | User-configurable workflow with dynamic phase selection |
| `issue_to_pr` | Fetch issue, decompose, execute, review, commit + open PR |
| `pr_review` | Fetch PR, fan-out parallel reviewers, synthesize verdict, escalate if needed |
| `meta_review` | Load a previous run, analyze, critique, and recommend improvements |
| `e2e_test` | Generate and run end-to-end tests with retry logic |
| `e2e_test_selector` | Select which E2E tests to run based on code changes |
| `devils_advocate` | Adversarial design review: research, critique, defend, judge |

## Configuration

Each workflow has a `config.yaml` that controls its behavior:

```yaml
workflow: default

phases:
  decompose:
    - MiniMax-M2.5-highspeed
  execute:
    - MiniMax-M2.5-highspeed
  review:
    - MiniMax-M2.5-highspeed
  critique:
    enabled: false
    models:
      - MiniMax-M2.5-highspeed
  test_gen:
    enabled: false
    models:
      - MiniMax-M2.5-highspeed
  verify:
    enabled: true

loops:
  max_critique_rounds: 1
  max_review_rounds: 2
  max_replan_rounds: 1

escalation:
  enabled: false
  confidence_threshold: 0.3
```

Phases list models in preference order (first available is used). Set `enabled: false` to skip optional phases. Loop limits prevent infinite review cycles.

Use `get_models_for_phase()` and `get_stall_config()` from `langgraph_maestro.core.config` to read these values programmatically.

## MC Agent

`mc.py` is the key differentiator -- it wraps Claude Code as a programmable agent API, using lightweight MCP tool schemas (~900 tokens) instead of Claude Code's built-in tools (~5,800 tokens per 5 tools).

### Programmatic usage

```python
from pathlib import Path
from langgraph_maestro.core.mc import build_cmd, run_claude, parse_usage

# Build the CLI command
cmd, prompt_text = build_cmd(
    "Fix the type error in auth.py",
    model="claude-sonnet-4-6",
)

# Run Claude Code as a sub-agent
final, elapsed, returncode = run_claude(
    cmd, cwd=Path("/path/to/repo"), timeout=300, prompt_stdin=prompt_text,
)
usage = parse_usage(final)
```

It also supports routing to local MLX models via RAC when the model name starts with `mlx-community/` or is set to `"local"`.

### As MCP server

```bash
python -m langgraph_maestro.core.mc --mcp-server
```

Claude Code spawns this automatically when configured as an MCP tool provider.

## Observability

The `infrastructure/` directory contains a Docker Compose stack for full observability:

```bash
cd infrastructure
cp .env.example .env  # Edit with your secrets
docker compose up -d
```

This starts:

| Service | Port | Purpose |
|---------|------|---------|
| Langfuse | 3100 | Trace viewer, prompt/response replay |
| Grafana | 3200 | Dashboards and alerting |
| Prometheus | 9091 | Metrics collection |
| ClickHouse | 8123 | Langfuse analytics backend |
| MinIO | 9090 | Object storage for Langfuse |

LLM calls emit OTel spans with GenAI semantic conventions (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc.). Set `MAESTRO_TRACE_CONTENT=false` in production to omit prompt/response content from spans.

## Custom workflows

Create a new workflow by adding a directory under `workflows/`:

```
src/langgraph_maestro/workflows/my_workflow/
  __init__.py
  config.yaml
  graph.py
  state.py
```

Minimal `graph.py`:

```python
from langgraph.graph import StateGraph, END
from langgraph_maestro.core.config import load_config, workflow_config_path

config = load_config(workflow_config_path(__file__))

def my_node(state: dict) -> dict:
    # Use call_llm(), call_llm_structured(), etc.
    return {"result": "done"}

builder = StateGraph(dict)
builder.add_node("my_node", my_node)
builder.set_entry_point("my_node")
builder.add_edge("my_node", END)

graph = builder.compile()

def run_workflow(task: str, **kwargs) -> dict:
    return graph.invoke({"task": task, **kwargs})
```

Register it by importing in `workflows/__init__.py`:

```python
from langgraph_maestro.workflows.my_workflow.graph import run_workflow as run_my_workflow
```

## License

MIT -- see [LICENSE](LICENSE).
