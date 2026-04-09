# langgraph-maestro

Multi-agent LLM workflow orchestration framework built on [LangGraph](https://github.com/langchain-ai/langgraph).

## Principles

### 1. Start Simple
Don't build an 11-node graph on day one. Start with a single agent, a clear task, and a ground truth file. Add decomposition when tasks are too big. Add adversarial review when outputs aren't trustworthy. Add context engineering when agents keep missing domain knowledge. Every node in the graph must earn its place by solving a problem that simpler approaches couldn't. The principles describe where you're going, not where you start.

### 2. One Agent, One Prompt, One Task
Each agent gets a single, focused job. No sprawling mega-prompts that plan, execute, review, and fix in one shot. LangGraph's value is decomposition: each node does one thing well, the graph handles orchestration. If a node is doing two things, split it into two nodes. No overlapping responsibilities between agents.

### 3. Closed-Loop Quality
Every output is verified against ground truth or evaluation criteria. Correctness over speed, always. A workflow that can't prove it succeeded hasn't.

- **Ground truth / reference files**: The agent needs something to compare against -- a KiCad schematic, a UART byte stream, expected test output, an acceptance criteria doc. Whatever "correct" looks like for this task.
  - *Ideal*: User provides ground truth alongside the task
  - *Acceptable*: Agent generates its own test/criteria first (TDD style)
  - *Last resort*: Agent stops and asks the human rather than producing unverifiable output
- **Execute, observe, compare, adjust**: No single-shot "here's my answer" workflows. Every action needs measurable feedback. Iterate in small pieces -- assess the whole problem, solve one piece, verify, step back, reassess, repeat.
- **Early stopping**: If no measurable progress after 1-2 iterations, stop. Escalate to a human, try a different approach, or declare the task blocked. If the loss plateaus, more epochs won't help.
- **Replace manual testing**: Ask "what would a real human do to test this?" and automate that. Real inputs, real systems, real outputs. The test must be trustworthy enough that you don't need to manually verify after.

**The user has a role here too.** They may need to provide reference files, install testing tools, or define what "real success" looks like. Workflows should be explicit about what they need from the user to close the loop.

### 4. Never Guess -- Always Look Up, Always Cite Sources
LLMs must never rely on training data for verifiable facts. If there's documentation, read it. If there's an API spec, fetch it. If there's a web page with the answer, search and scrape it. The self-hosted SearXNG + Crawl4AI stack exists for exactly this -- every agent can search the web and verify claims at zero cost. Memory is for reasoning, not for facts.

Every agent should actively search for evidence to support its approach. Not "I think this is correct" but "according to [source], this is the documented way to do it." Structure output so verification is trivial -- immediately validatable, not just asserted. If an agent can't find evidence, that's a signal the approach might be wrong.

### 5. Design for LLM Consumption
Everything in this framework is built by LLMs and for LLMs. Every interface is designed for LLM callers first, human readers second.

- **Semantic naming**: Function names are documentation. `validate_uart_packet_checksum()` not `check()`. An LLM reads the name and knows what it does.
- **Structured errors with suggested fixes**: Not `Error: failed` but `Error: UART checksum mismatch — expected 0x4A, got 0x3F at byte offset 127. Likely cause: baud rate mismatch.`
- **Self-documenting tool schemas**: Descriptive parameter names, unambiguous descriptions, minimal required context. An LLM should be able to use a tool correctly from its schema alone.
- **Self-documenting file structure**: An LLM should understand the codebase from the directory tree alone.
- **Comments explain WHY, not what**: The LLM can read the code — tell it why you made this choice, what alternatives you rejected, what constraints drove the decision.

### 6. Context Engineering
Output quality = context quality. A mediocre model with perfect context beats a great model with vague context. Fill the context window with just the right information for the next step.

Four strategies:
1. **Write context**: Scratchpads, external memory, state files that persist across context boundaries
2. **Select context**: Just-in-time retrieval -- search the web, read docs, pull in only what's relevant for *this* step
3. **Compress context**: Summarize long conversations, drop irrelevant history, keep the signal-to-noise ratio high
4. **Isolate context**: Token-heavy operations go to sub-agents with focused context windows, not the main orchestrator

After each attempt, analyze what the agent didn't know. Research more, rebuild a *better* agent with the gaps filled. The agent itself evolves across iterations, not just the feedback it receives. The "research and build agent" step is where most of the intelligence lives.

### 7. Adversarial Review -- Always
Every critical output gets challenged by a different agent with a different prompt (and ideally a different model). The agent that wrote the code never approves it. Find what's wrong, what's hallucinated, what's bullshit. This isn't an optional "nice to have" review phase -- it's built into the loop. Use LLM-as-Judge patterns and golden response comparisons where appropriate.

### 8. Self-Improving Workflows
Workflows are not static. Every run is an opportunity to improve the system:

- **Extract deterministic tools**: When an LLM consistently produces the same transformation, write a Python script. Every repeated LLM call is a candidate for a reliable, deterministic replacement.
- **Curate tools per agent**: Don't give every agent every tool. The planner selects the specific tools each agent needs. Fewer, better tools outperform large toolboxes. Track tool usage and success rates.
- **Specialize agents over time**: Generic agents become domain experts. Research results become baked-in context. One-off prompts become battle-tested templates.
- **Evolve the graph itself**: Add new nodes, remove ineffective ones, change routing logic based on what actually works.

The goal: LLMs handle novel reasoning, deterministic tools handle everything else. The system gets faster, cheaper, and more reliable with each run.

### 9. Human-in-the-Loop Is a Feature
The system should know when to stop and ask. When confidence is low, when verification fails, when the task is ambiguous -- pause, checkpoint state, and ask the human. This is not a failure mode. It's the most reliable path to quality. LangGraph's `interrupt()` with SQLite checkpointing makes this a first-class capability: the workflow pauses, the human provides input, and the workflow resumes exactly where it left off.

### 10. Observe Everything
Every LLM call, tool invocation, state transition, and cost is traced with structured logs and correlation IDs across the full graph. If you can't see what happened, you can't fix what broke. Observability is not optional infrastructure -- it's how you debug non-deterministic systems.

- **Structured logs**: Logs must contain enough context that an LLM reading them can understand what happened without seeing the source code. Include inputs, outputs, decisions, and deltas.
- **Token and cost tracking**: Track per-step token usage and costs. Set budget guardrails per run and per day. Agents make 3-10x more LLM calls than chatbots -- costs compound with retries, adversarial review, and closed-loop iteration.
- **OTel tracing**: Every prompt, response, token count, and latency is recorded via OpenTelemetry with GenAI semantic conventions. Langfuse for trace replay, Grafana for dashboards, Prometheus for metrics.

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
