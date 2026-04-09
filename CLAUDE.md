# langgraph-maestro

Multi-agent LLM workflow orchestration framework built on LangGraph. Provides a provider-routed `call_llm()` interface, config-driven workflow graphs, structured output with auto-retry, stall/budget detection, and OTel tracing. Ships with 9 built-in workflows (chain-of-thought, issue-to-PR, PR review, etc.) and a CLI (`maestro`) for running them.

## Core Principles

These principles govern every workflow, every agent, and every design decision in this framework. They are non-negotiable.

1. **LLM-First Development** -- Everything is built by LLMs and for LLMs. Semantic function names (`validate_uart_checksum()` not `check()`), structured logs with full context, diagnostic error messages, self-documenting file structure, comments that explain WHY not what. Every symbol carries meaning. An LLM should understand the codebase from the directory tree alone.

2. **Quality Over Everything** -- If the output can't be trusted, it's worthless. Correctness over speed, always. A workflow that can't prove it succeeded hasn't.

3. **Never Guess -- Always Look Up, Always Cite Sources** -- Never rely on LLM training data for verifiable facts. Search the web (`web_search()`), read docs (`web_scrape()`), check the actual source. Memory is for reasoning, not facts. Every agent must find evidence for its approach -- "according to [source]" not "I think." If you can't find evidence, the approach might be wrong.

4. **One Agent, One Prompt, One Task** -- Each node does one focused job. If it's doing two things, split it. The graph handles orchestration. Models do better when limited to one thing with excellent context about that one thing.

5. **Closed-Loop Feedback** -- Every action needs measurable feedback:
   - Ground truth / reference files to compare against (user-provided ideal, LLM-generated acceptable, stop-and-ask last resort)
   - Logs as the primary feedback mechanism -- if the agent can't see it, it can't learn from it
   - Tests that run against real systems and produce measurable results
   - The user may need to help set up testing infrastructure

6. **Iterative, Not Waterfall** -- Assess the whole problem → research → solve one small piece → verify → step back → reassess → repeat. Early stopping: no progress after 1-2 iterations = stop and escalate. Same as ML training -- if loss plateaus, more epochs won't help.

7. **Adversarial Review -- Always** -- Every output gets challenged by a different agent. The agent that wrote the code never approves it. Find what's wrong, what's hallucinated, what's bullshit.

8. **Context Engineering** -- Output quality = context quality. Before executing, invest in building the agent's context: research the domain, gather specific facts, construct a specialized prompt. After each attempt, analyze what the agent didn't know, research more, rebuild a better agent. The agent itself evolves, not just the feedback.

9. **Self-Improving Workflows** -- Workflows are not static. After every run: review what worked, what failed, what context was missing. Build deterministic tools (Python scripts, bash, daemons) to replace repeated LLM calls. Grow a tool library and curate which tools each agent gets -- customized context + curated tools = specialized agents. LLMs handle novel reasoning; deterministic tools handle everything else. The system gets more reliable with each run.

10. **Start Simple** -- Don't build an 11-node graph on day one. Start with one agent, one task, one ground truth. Add complexity only when simpler approaches fail. Every node must earn its place.

11. **Human-in-the-Loop Is a Feature** -- The system should know when to stop and ask. Low confidence, failed verification, ambiguous task → pause, checkpoint, ask the human. This is the most reliable path to quality, not a failure mode.

12. **Real-World E2E Testing** -- "What would a real human do to test this?" Automate that. Not mocked unit tests -- real inputs, real systems, real outputs. The test must be trustworthy enough to replace manual verification.

When building or modifying workflows, ask: Does this design honor all 12 principles? If not, fix it before proceeding.

## Quick reference

```bash
# Install
uv sync

# Run all tests
uv run pytest

# Skip slow / tracing tests
uv run pytest -m "not slow"
uv run pytest -m "not tracing"

# Coverage
uv run pytest --cov=langgraph_maestro

# List workflows
uv run maestro list

# Run a workflow
uv run maestro run default --task "Fix the login bug" --cwd ./my-repo

# Scaffold a new workflow
uv run maestro init --name my_workflow
```

Build backend is `hatchling`; package manager is `uv`. Python 3.11+.

## Package structure

```
src/langgraph_maestro/
  cli.py                 # CLI entry point (maestro command)
  core/                  # Foundation modules
    config.py            # YAML config loader, workflow_config_path()
    llm.py               # Provider registry, call_llm(), call_llm_with_fallback()
    structured.py        # Pydantic-validated LLM output with auto-retry
    mc.py                # Claude Code as programmable agent (build_cmd/run_claude)
    registry.py          # Workflow registry (register_workflow/get_workflow)
    stall.py             # Timeout/loop/no-progress detection
    budget.py            # Per-run and daily token budget guards
    tracing.py           # OTel tracer setup (Langfuse integration)
    pe.py                # Prompt engineering / improvement
    skills.py            # Skill injection for agent prompts
    schemas.py           # Pydantic models for structured output
    state.py             # Shared state schemas
    checkpointer.py      # SQLite-backed LangGraph checkpointing
    runner.py            # Unified workflow runner
    logging.py           # Logging setup
  nodes/                 # Reusable LangGraph nodes (decompose, execute, review, ...)
  workflows/             # Self-contained workflow packages
    default/             # Each has: __init__.py, config.yaml, graph.py, state.py
    chain_of_thought/
    issue_to_pr/
    pr_review/
    meta_review/
    e2e_test/
    e2e_test_selector/
    customize/
    devils_advocate/
tests/
  conftest.py            # Shared fixtures (mock_llm, tmp_config, disable_pe)
  unit/                  # Unit tests
infrastructure/          # Docker Compose for Langfuse + Grafana + Prometheus
```

## Import conventions

```python
# Core utilities — direct imports
from langgraph_maestro.core.config import load_config, workflow_config_path, get_models_for_phase
from langgraph_maestro.core.llm import call_llm, call_llm_with_fallback
from langgraph_maestro.core.structured import call_llm_structured
from langgraph_maestro.core.stall import StallDetector
from langgraph_maestro.core.mc import build_cmd, run_claude, parse_usage
from langgraph_maestro.core.registry import register_workflow

# Lazy-loaded from core __init__.py (these use __getattr__ lazy loading)
from langgraph_maestro.core import setup_logging, get_logger, StallDetector, load_config

# Nodes
from langgraph_maestro.nodes.decompose import make_decompose_node
from langgraph_maestro.nodes.execute import execute
from langgraph_maestro.nodes.review import review

# Workflows
from langgraph_maestro.workflows import run_default, run_issue_to_pr
```

## Config paths

Workflows resolve their `config.yaml` using `workflow_config_path(__file__)`. This finds `config.yaml` in the same directory as the calling module:

```python
from langgraph_maestro.core.config import load_config, workflow_config_path

# In a workflow's graph.py:
config = load_config(workflow_config_path(__file__))
```

Each workflow directory has its own `config.yaml` with phase models, loop limits, and feature flags. Use `get_models_for_phase("execute", config)` and `get_stall_config(config)` to read values programmatically.

## Adding a new workflow

1. Create the directory under `src/langgraph_maestro/workflows/my_workflow/`.
2. Add four files:

**`config.yaml`** -- phase models, loop limits, feature flags:
```yaml
workflow: my_workflow
phases:
  analyze:
    - MiniMax-M2.5-highspeed
  synthesize:
    - MiniMax-M2.5-highspeed
loops:
  max_review_rounds: 2
```

**`state.py`** -- TypedDict state schema:
```python
from typing import TypedDict, Optional

class MyWorkflowState(TypedDict, total=False):
    task: str
    cwd: Optional[str]
    config_path: Optional[str]
    result: str
```

**`graph.py`** -- LangGraph StateGraph definition:
```python
from langgraph.graph import StateGraph, END
from langgraph_maestro.core.config import load_config, workflow_config_path

config = load_config(workflow_config_path(__file__))

def my_node(state: dict) -> dict:
    return {"result": "done"}

builder = StateGraph(dict)
builder.add_node("my_node", my_node)
builder.set_entry_point("my_node")
builder.add_edge("my_node", END)

graph = builder.compile()

def build_graph(**kwargs):
    return graph

def run_workflow(task: str, **kwargs) -> dict:
    return graph.invoke({"task": task, **kwargs})
```

**`__init__.py`** -- register the workflow:
```python
from .graph import build_graph, run_workflow
from langgraph_maestro.core.registry import register_workflow
from langgraph_maestro.core.config import workflow_config_path

register_workflow(
    "my_workflow",
    build_graph,
    default_config=workflow_config_path(__file__),
    description="One-line description of what this workflow does.",
)

__all__ = ["build_graph", "run_workflow"]
```

3. Import the package in `workflows/__init__.py` so registration runs on import.

Or use `maestro init --name my_workflow` to scaffold this automatically.

## Adding a new node

Nodes use a factory pattern. The factory takes config and returns a closure that operates on state:

```python
# src/langgraph_maestro/nodes/my_node.py
import logging
from typing import Any, Callable, Type
from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.structured import call_llm_structured

logger = logging.getLogger(__name__)

def make_my_node(
    config_path_default: str,
    schema_class: Type[Any],
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a my_node with the given configuration."""

    def my_node(state: dict) -> dict:
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("my_phase", config)

        result = call_llm_structured(
            prompt=state["task"],
            models=models,
            response_model=schema_class,
            phase="my_phase",
            config=config,
        )
        return {"result": result.model_dump()}

    return my_node
```

Then use it in a workflow's `graph.py`:

```python
my_node = make_my_node(config_path, MySchema, prompts_dir)
builder.add_node("my_node", my_node)
```

## Adding a new LLM provider

Providers are registered in `core/llm.py` via `register_provider()`. A provider is a callable with signature `(prompt, model, **kwargs) -> dict`:

```python
from langgraph_maestro.core.llm import register_provider

def my_provider(prompt: str, model: str, **kwargs) -> dict:
    # Call the LLM API
    return {
        "content": "response text",
        "model": model,
        "latency": 0.5,
        "input_tokens": 100,
        "output_tokens": 50,
    }

register_provider("my_provider", my_provider)
```

Routing in `get_provider()` maps model strings to providers. Add routing logic there if the model name doesn't match an existing prefix pattern.

Built-in providers: `claude_code` (default), `minimax`, `local` (MLX via RAC), `codex` (OpenAI/GPT).

## Key patterns

**`call_llm(prompt, model, ...)`** -- Single LLM call through the provider registry. Emits OTel spans with GenAI semantic conventions. All LLM calls must go through this.

**`call_llm_with_fallback(prompt, models, ...)`** -- Takes a list of models in preference order. Tries each until one succeeds. Used by most nodes.

**`call_llm_structured(prompt, models, response_model, ...)`** -- Calls `call_llm_with_fallback`, parses JSON from response, validates against a Pydantic model. On validation failure, re-injects the error and retries (Instructor-style).

**`mc.py: build_cmd() / run_claude()`** -- Wraps Claude Code as a programmable agent API. `build_cmd()` assembles the CLI command with MCP tool server (~900 tokens vs ~5,800 for built-in tools). `run_claude()` executes it, streams NDJSON output, and returns `(final_message, elapsed, returncode)`. `parse_usage()` extracts token counts and cost from the result.

**`workflow_config_path(__file__)`** -- Resolves `config.yaml` relative to the calling module. Every workflow uses this pattern.

**`register_workflow(name, build_fn, ...)`** -- Adds a workflow to the global registry. Called in each workflow's `__init__.py`. The CLI discovers workflows by importing `langgraph_maestro.workflows` which triggers all registrations.

## Testing conventions

### Fixtures (in `tests/conftest.py`)

**`mock_llm`** -- Patches `_providers` dict in `core/llm.py` to replace all providers with a mock. Returns a list you append responses to:
```python
def test_something(mock_llm):
    mock_llm.append({"content": "planned response", "model": "mock", "latency": 0.1})
    # Now call code that uses call_llm() -- it will consume from the list
```

**`mock_llm_json`** -- Convenience wrapper that JSON-encodes a dict for you:
```python
def test_structured(mock_llm_json):
    mock_llm_json({"subtasks": ["a", "b"]})
```

**`tmp_config`** -- Creates a temporary `config.yaml` and clears the config cache:
```python
def test_with_config(tmp_config, mock_llm):
    path = tmp_config({"phases": {"decompose": ["mock-model"]}, "loops": {"max_review_rounds": 1}})
    # path is a string to the temp config.yaml
```

**`disable_pe`** (autouse) -- Automatically patches `improve_prompt` to be a no-op in all tests. Tests that need real PE behavior use `@pytest.mark.enable_pe`.

### Markers

- `@pytest.mark.slow` -- Long-running tests. Skip with `-m "not slow"`.
- `@pytest.mark.tracing` -- Needs Langfuse/OTel running. Skip with `-m "not tracing"`.
- `@pytest.mark.enable_pe` -- Opts out of the `disable_pe` autouse fixture.

### Mocking LLM calls

Never call real LLM APIs in unit tests. Use `mock_llm` to control responses. For structured output tests, pre-load valid JSON that matches the expected Pydantic schema:
```python
def test_decompose(mock_llm, tmp_config):
    mock_llm.append({
        "content": '{"subtasks": [{"name": "step1", "description": "do thing"}]}',
        "model": "mock",
        "latency": 0.1,
    })
    # invoke the node...
```

## Don'ts

- **Don't hardcode config paths.** Use `workflow_config_path(__file__)` or accept a `config_path` parameter. Tests use `tmp_config` to inject temporary configs.
- **Don't import heavy modules at module level in CLI.** The CLI (`cli.py`) uses lazy imports inside command functions to keep `maestro --help` fast.
- **Don't add heavy dependencies.** Core deps are minimal (langgraph, pyyaml, anthropic, pydantic, opentelemetry). Check `pyproject.toml` before adding anything.
- **Don't call provider APIs directly.** All LLM calls go through `call_llm()` or `call_llm_structured()` so tracing, budgets, and fallback work.
- **Don't use `print()`.** Use `logging.getLogger(__name__)` for all output.
- **Don't put JSON or TOML config in workflows.** All workflow config is YAML.
- **Don't skip the config cache.** Call `clear_cache()` (from `core.config`) in tests after writing new config files. The `tmp_config` fixture handles this automatically.
