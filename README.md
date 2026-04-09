# langgraph-maestro

Multi-agent LLM workflow orchestration framework built on [LangGraph](https://github.com/langchain-ai/langgraph).

## Principles

### 1. LLM-First Development
Everything in this framework is built by LLMs and for LLMs. Every design decision must consider: "Can an LLM understand this?"

- **Semantic naming**: Function names are documentation. `validate_uart_packet_checksum()` not `check()`. An LLM reads the name and knows what it does.
- **Structured, readable logs**: Logs must contain enough context that an LLM reading them can understand what happened without seeing the source code. Include inputs, outputs, decisions, and deltas.
- **Diagnostic error messages**: Not `Error: failed` but `Error: UART checksum mismatch — expected 0x4A, got 0x3F at byte offset 127. Likely cause: baud rate mismatch.`
- **Self-documenting file structure**: An LLM should understand the codebase from the directory tree alone.
- **Comments explain WHY, not what**: The LLM can read the code — tell it why you made this choice, what alternatives you rejected, what constraints drove the decision.
- **Semantic sentinels**: Named constants, typed return values, descriptive variable names. Every symbol an LLM encounters should carry meaning.

### 2. Quality Over Everything
If you can't trust the output, it's worthless -- you need human effort to verify it anyway, which defeats the purpose. Every design decision prioritizes correctness over speed. A slow, verified result beats a fast, wrong one. If a workflow can't prove it succeeded, it hasn't.

### 3. Never Guess -- Always Look Up, Always Cite Sources
LLMs must never rely on training data for verifiable facts. If there's documentation, read it. If there's an API spec, fetch it. If there's a web page with the answer, search and scrape it. The self-hosted SearXNG + Crawl4AI stack exists for exactly this -- every agent can search the web and verify claims at zero cost. Memory is for reasoning, not for facts.

Every agent should actively search for evidence to support its approach. Not "I think this is correct" but "according to [source], this is the documented way to do it." When an agent chooses an implementation pattern, it should find proof that the pattern works -- a docs page, a Stack Overflow answer, a GitHub example. If it can't find evidence, that's a signal the approach might be wrong.

Search is free and local (SearXNG + Crawl4AI), so prefer re-searching over assuming. Future optimization: cache research results to avoid redundant lookups across agents working on the same problem.

### 4. One Agent, One Prompt, One Task
Each agent gets a single, focused job. No sprawling mega-prompts that plan, execute, review, and fix in one shot. LangGraph's value is decomposition: each node does one thing well, the graph handles orchestration. If a node is doing two things, split it into two nodes.

### 5. Closed-Loop Feedback
Every action needs observable, measurable feedback. No single-shot "here's my answer" workflows.

- **Ground truth / reference files**: The agent needs something to compare against. A KiCad schematic, a UART byte stream, expected test output, an acceptance criteria doc -- whatever "correct" looks like for this task.
  - *Ideal*: User provides ground truth alongside the task
  - *Acceptable*: Agent generates its own test/criteria first (TDD style)
  - *Last resort*: Agent stops and asks the human rather than producing unverifiable output
- **Logs are the agent's eyes**: Every LLM call, tool invocation, decision point, and iteration delta gets logged. If the agent can't see it in the logs, it can't learn from it. Logging is not an afterthought -- it's the primary feedback mechanism.
- **Tests as verification**: Not "I think this works" -- run it, measure it, compare the output to the reference. Real execution, real results.

**The user has a role here too.** They may need to provide reference files, install testing tools, or define what "real success" looks like. Workflows should be explicit about what they need from the user to close the loop.

### 6. Iterative, Not Waterfall
Work like a real engineer: look at the whole problem, research what you don't know, solve one small piece, verify it, step back, reassess, repeat.

Each iteration:
1. Assess the full problem (not just the current subtask)
2. Research what you need (docs, web, existing code)
3. Solve one small, testable piece
4. Verify it against the ground truth
5. Step back, look at the whole picture again, repeat

**Early stopping**: If no measurable progress after 1-2 iterations, stop. Don't keep grinding -- either escalate to a human, try a completely different approach, or declare the task blocked. Same principle as ML training: if the loss plateaus, more epochs won't help.

### 7. Adversarial Review -- Always
Every output gets challenged by a different agent whose job is to find what's wrong, what's hallucinated, what's bullshit. This isn't an optional "nice to have" review phase. It's built into the loop. The agent that wrote the code never approves it.

### 8. Context Engineering
The quality of the output is directly proportional to the quality of the context. A mediocre model with perfect context beats a great model with vague context.

Before any agent executes, invest in building its context:
1. **Research phase**: Search the web, read docs, find prior art, gather domain-specific knowledge
2. **Build a specialized agent**: Construct a system prompt with all relevant context baked in -- not generic instructions, but specific facts, constraints, and examples for *this* problem
3. **Review and rebuild**: After the first attempt, analyze what the agent didn't know. Research more, build a *better* agent with the gaps filled. The agent itself evolves across iterations, not just the feedback it receives.

This means the "research and build agent" step is where most of the intelligence lives. Execution is almost mechanical once the context is right.

### 9. Self-Improving Workflows
Workflows are not static. Every run is an opportunity to improve the system:

- **After-action review**: What worked? What failed? What context was missing? Capture learnings.
- **Build deterministic tools**: If an LLM keeps doing the same analysis, write a Python script. If it keeps searching for the same docs, cache them. Every repeated LLM call is a candidate for a reliable, deterministic replacement.
- **Specialize agents over time**: Generic agents become domain experts. Research results become baked-in context. One-off prompts become battle-tested templates.
- **Evolve the graph itself**: Add new nodes, remove ineffective ones, change routing logic based on what actually works. The workflow that runs on day 30 should be fundamentally better than day 1.

The goal: LLMs handle novel reasoning, deterministic tools handle everything else. Over time, more work shifts from LLM to tool.

### 10. Real-World E2E Testing
Ask: "What would a real human user do to test this?" Then automate that. The goal is to replace manual human testing entirely -- the automated test must be trustworthy enough that you don't need to manually verify after. Not mocked unit tests on fake data -- real inputs through the real system producing real outputs. When you can't fully automate it, be explicit about what the user needs to help set up.

## Features

- **Ground-truth-driven execution** -- agents define success criteria before working, test against reference outputs, and stop to ask when uncertain
- **Multi-provider LLM routing** -- call Claude, Codex/GPT, MiniMax, or local MLX models through a unified `call_llm()` interface with automatic fallback chains
- **MC agent** -- run Claude Code CLI as a programmable API with 84% fewer tool-schema tokens via lightweight MCP tool schemas (~900 tokens vs ~5,800)
- **Durable checkpointing** -- SQLite-backed state persistence for pause/resume, crash recovery, and human-in-the-loop workflows
- **Full observability** -- OpenTelemetry tracing with Langfuse integration, Grafana dashboards, Prometheus metrics. Every prompt, response, token count, and latency is recorded.
- **Config-driven workflows** -- YAML files define phases, models, loop limits, and optional stages per workflow
- **Stall and budget detection** -- automatic timeout, no-progress, and loop detection; per-run and daily token budget guards
- **Structured output** -- Pydantic schema validation with auto-retry on parse failures
- **9 built-in workflows** -- from simple chain-of-thought to full issue-to-PR automation
- **Web search & verification** -- self-hosted SearXNG + Crawl4AI for web search and scraping. Zero API costs, zero rate limits. Workflows can verify claims against live web sources.
- **One-command infrastructure** -- `./infrastructure/setup.sh` installs Docker, generates secrets, and starts Langfuse + Grafana + Prometheus

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
ANTHROPIC_API_KEY=sk-...          # Required for Claude API (or use Claude Code CLI subscription)
MINIMAX_API_KEY=...               # Optional — only for MiniMax models
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
    - claude-sonnet-4-6          # Primary model (fallback chain — tries in order)
  execute:
    - claude-sonnet-4-6
  review:
    - claude-sonnet-4-6
  critique:
    enabled: false               # Enable for adversarial review
    models:
      - claude-sonnet-4-6
  test_gen:
    enabled: false               # Enable for TDD (generate tests before execute)
    models:
      - claude-sonnet-4-6
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

### Web search & scraping (optional)

Enable self-hosted web search and scraping for workflow verification:

```bash
cd infrastructure
docker compose --profile search up -d
```

This adds:

| Service | Port | Purpose |
|---------|------|---------|
| SearXNG | 8888 | Meta-search engine (Google, Bing, DuckDuckGo, etc.) |
| Crawl4AI | 11235 | Web scraping with clean markdown output |

Use in your workflows:

```python
from langgraph_maestro.core.web import web_search, web_scrape, search_and_extract

# Search
results = web_search("LangGraph checkpointing best practices")

# Scrape a URL to clean markdown
page = web_scrape("https://docs.example.com/guide")

# Search + scrape top results in one call
findings = search_and_extract("how to implement HITL", max_results=3)
```

Content is automatically truncated to prevent context window blowup. Configure via env vars:

```bash
MAESTRO_SEARXNG_URL=http://localhost:8888    # SearXNG endpoint
MAESTRO_CRAWL4AI_URL=http://localhost:11235  # Crawl4AI endpoint
```

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
