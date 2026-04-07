# langgraph-maestro

Multi-agent LLM workflow orchestration framework built on LangGraph.

## Package structure

```
src/langgraph_maestro/
  __init__.py              # Version, top-level exports
  core/                    # Foundation modules
    config.py              # YAML config loader, workflow_config_path()
    llm.py                 # Multi-provider LLM calls with OTel tracing
    mc.py                  # Claude Code as programmable agent API
    stall.py               # Timeout/loop/no-progress detection
    budget.py              # Per-run and daily token budget guards
    structured.py          # Pydantic-validated LLM output with auto-retry
    tracing.py             # OTel tracer setup (Langfuse integration)
    checkpointer.py        # SQLite-backed LangGraph checkpointing
    runner.py              # Unified workflow runner (trace + checkpoint + invoke)
    state.py               # Shared state schemas
    schemas.py             # Pydantic models for structured output
    pe.py                  # Prompt engineering / improvement
    skills.py              # Skill injection for agent prompts
    registry.py            # Workflow registry
    logging.py             # Logging setup
  nodes/                   # Reusable LangGraph nodes
    decompose.py, execute.py, review.py, critique.py, ...
  workflows/               # Self-contained workflow packages
    default/               # Each has: config.yaml, graph.py, state.py
    chain_of_thought/
    issue_to_pr/
    pr_review/
    meta_review/
    e2e_test/
    e2e_test_selector/
    customize/
    devils_advocate/
tests/                     # Test suite
infrastructure/            # Docker Compose for Langfuse + Grafana + Prometheus
```

## Running tests

```bash
uv run pytest                          # All tests
uv run pytest -m "not slow"            # Skip slow tests
uv run pytest -m "not tracing"         # Skip tests needing Langfuse/OTel
uv run pytest --cov=langgraph_maestro  # With coverage
```

## Import conventions

```python
# Core utilities
from langgraph_maestro.core.config import load_config, workflow_config_path, get_models_for_phase
from langgraph_maestro.core.llm import call_llm, call_llm_with_fallback
from langgraph_maestro.core.structured import call_llm_structured
from langgraph_maestro.core.stall import StallDetector
from langgraph_maestro.core.tracing import get_tracer
from langgraph_maestro.core.mc import run_mc_agent

# Lazy-loaded from core __init__.py
from langgraph_maestro.core import setup_logging, get_logger, StallDetector, load_config

# Nodes
from langgraph_maestro.nodes.decompose import decompose
from langgraph_maestro.nodes.execute import execute
from langgraph_maestro.nodes.review import review

# Workflows
from langgraph_maestro.workflows import run_default, run_issue_to_pr, run_pr_review
```

## Config paths

Workflows resolve their `config.yaml` using `workflow_config_path(__file__)`:

```python
from langgraph_maestro.core.config import load_config, workflow_config_path

# In a workflow's graph.py -- resolves config.yaml relative to the calling file
config = load_config(workflow_config_path(__file__))
```

This finds `config.yaml` in the same directory as the calling module. Each workflow directory contains its own `config.yaml` with phase models, loop limits, and feature flags.

## Key conventions

- Python 3.11+ required
- Pydantic v2 for all data models and structured output
- YAML for all workflow configuration (not JSON, not TOML)
- OTel GenAI semantic conventions for all LLM call tracing
- `hatchling` as build backend; `uv` as package manager
- `os.Logger` style logging via `get_logger()` -- no `print()` statements
- All LLM calls go through `call_llm()` or `call_llm_structured()` -- never call provider APIs directly
