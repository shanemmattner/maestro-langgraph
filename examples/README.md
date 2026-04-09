# Workflow Examples

Each directory is a self-contained workflow example that demonstrates a different LangGraph pattern.

## Usage

Copy any example directory and modify it for your use case. Examples import from `langgraph_maestro.core` for LLM calls, tracing, checkpointing, and other core utilities.

## Examples

| Directory | Description |
|-----------|-------------|
| `adaptive/` | Core adaptive loop: think, plan, adversarial review, act+verify per piece |
| `chain_of_thought/` | Structured step-by-step reasoning: decompose question, reason each step, synthesize — simplest workflow, good starter |
| `pr_review/` | PR code review with parallel reviewer personas, synthesis, and escalation — read-only pattern |

## Structure

Each example contains:

- `graph.py` — Graph definition with `build_graph()` and optional `run_workflow()` convenience function
- `nodes.py` — Node implementations with `DEFAULT_MODELS` constant (no config.yaml dependency)
- `state.py` — TypedDict state definition
- `run.py` — Simple entry point to run the workflow
- `prompts/` — Prompt templates (where applicable)

## Key Differences from Source Workflows

- No `config.yaml` files — models and loop limits are hardcoded constants
- No `register_workflow()` calls — no registry dependency
- No `config_path` parameters in state or function signatures
- All examples use `DEFAULT_MODELS = ["claude-sonnet-4-6"]`
- Loop limits are module-level constants (e.g., `MAX_RETRIES = 2`)
