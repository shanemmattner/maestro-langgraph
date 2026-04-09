# PRD: Maestro

## What It Is

Maestro is a reference repository for building LLM-powered engineering workflows. It contains principles, useful tools, and example workflows that agents and developers can learn from and adapt to any project.

It is NOT a framework. There are no config files, no registries, no schemas to conform to. It's a collection of battle-tested tools and patterns.

The primary use case: point an agent at this repo and say "Read the principles, look at the examples, then build me custom workflows for my project."

## What's In The Repo

### Principles

10 principles for building effective agentic workflows, distilled from experience building multiple agent harnesses:

1. **Start Simple** -- Begin with a single LLM call. Add complexity only when needed.
2. **One Agent, One Task** -- Each agent has a clear, focused responsibility.
3. **Closed-Loop Quality** -- Every output gets verified. Tests, reviews, and checks close the loop.
4. **Never Guess -- Cite Sources** -- Ground claims with web search, file reads, or tool output. Never hallucinate facts.
5. **Design for LLM Consumption** -- Prompts, docs, and state should be text that LLMs can read and act on.
6. **Context Engineering** -- Write, select, compress, and isolate context deliberately. Don't dump everything into the prompt.
7. **Adversarial Review** -- Always have a second agent challenge the plan before executing. The session that wrote it must never review it.
8. **Self-Improving Workflows** -- After-action reviews capture what worked and what didn't. Feed lessons back into prompts.
9. **Human-in-the-Loop** -- Humans make judgment calls. Agents do the work. Design clear handoff points.
10. **Observe Everything** -- Trace every LLM call, track tokens and costs, log decisions. You can't improve what you can't see.

### Tools

Python modules that provide useful capabilities:

| Module | Purpose |
|--------|---------|
| `llm.py` | Provider-agnostic LLM calls (Claude Code, local models, MiniMax, Codex). Fallback chains. `extract_json()` and `rescue_json()` for permissive text parsing. |
| `mc.py` | Claude Code sub-agent wrapper with 84% token savings on tool schemas. |
| `tracing.py` | OpenTelemetry spans + Langfuse integration. `trace_node()` decorator for automatic tracing. |
| `web.py` | Web search via SearXNG + web scraping via Crawl4AI. Self-hosted, no API keys needed. |
| `stall.py` | Detects stuck workflows: timeouts, no-progress loops, repeated states. |
| `budget.py` | Token budget guards. Per-run and daily limits. |
| `ratelimit.py` | Rate limit detection with exponential backoff. |
| `checkpointer.py` | LangGraph checkpointer factory (SQLite or memory). |
| `verify.py` | Code verification: py_compile for syntax, pytest for tests. |
| `lint.py` | Prompt quality linter. Zero dependencies, pure function. |
| `structured.py` | Optional Pydantic validation with auto-retry for when you want structured output. |
| `workspace.py` | Git workspace management (clone, branch, commit). |
| `eval.py` | LLM-as-judge evaluation with Langfuse score logging. |
| `prompts.py` | Langfuse prompt versioning with local file fallback. |
| `logging.py` | JSON-line rotating file logger. |

### Example Workflows

Self-contained LangGraph workflows that demonstrate the principles. Each is a directory with Python files + markdown prompts. Copy one and modify it.

| Example | Pattern | When to use |
|---------|---------|-------------|
| `adaptive` | think -> plan <-> adversarial review -> act <-> verify | General task execution -- features, bugs, refactors |
| `pr-review` | fan-out -> analyze -> synthesize | Read-only code review |
| `chain-of-thought` | think -> reason -> conclude | Simplest workflow, good starting point |

Each example uses `DEFAULT_MODELS = ["claude-sonnet-4-6"]` as a Python constant. Change the model by editing the constant. Change the behavior by editing the markdown prompts. No config files.

### Infrastructure (Docker)

Docker Compose stack for observability and web search:

| Service | Purpose |
|---------|---------|
| Langfuse | Trace and observe every LLM call, view in dashboard |
| SearXNG | Self-hosted web search (no API keys) |
| Crawl4AI | Web page scraping |
| Grafana | Metrics dashboards |
| Prometheus | Metrics collection |

Start with: `docker compose up -d`
View traces at: http://localhost:3000 (Langfuse)
View dashboards at: http://localhost:3001 (Grafana)

## How To Use It

### For your own projects

1. Clone this repo
2. `docker compose up -d` (for observability + web search)
3. Read the principles
4. Copy an example workflow
5. Modify the Python and markdown prompts for your use case
6. Run it

### With an AI agent

1. Point the agent at this repo
2. Tell it: "Read the principles and examples in the maestro repo. Build custom workflows for this project."
3. The agent reads, learns the patterns, and creates bespoke workflows tailored to your codebase

## Design Decisions

**No YAML config files.** Models, loop limits, and settings are Python constants. Change them by editing Python code. This is intentional -- config files add indirection and eventually become a maintenance burden.

**No Pydantic schemas for LLM output.** Nodes use `call_llm_with_fallback()` + `extract_json()` for permissive text parsing. LLMs work with text. Structured output validation adds fragility without proportional value. `structured.py` is available for the rare cases where you genuinely need it.

**No workflow registry.** There's no `maestro run <name>`. Each example has its own `run.py`. This is simpler and doesn't require framework knowledge.

**LangGraph for the graph, not for opinions.** LangGraph provides graph structure, checkpointing, and Langfuse integration. We use it as plumbing, not as an architecture. Workflows are small Python files, not complex state machines.

**Markdown prompts are the product.** The prompts in each workflow's `prompts/` directory are what determine quality. Invest time in writing good prompts, not in framework configuration.

## What It's Not

- Not a framework you install and configure
- Not a replacement for Claude Code, Aider, or Cursor
- Not an enterprise platform
- Not trying to support every LLM provider (use LiteLLM as an escape hatch)

## Tech Stack

- **Python 3.11+**
- **LangGraph** -- workflow graphs, checkpointing
- **Langfuse** -- observability, tracing
- **OpenTelemetry** -- distributed tracing
- **Docker** -- infrastructure services
- **SearXNG** -- web search
- **Crawl4AI** -- web scraping
- **Grafana + Prometheus** -- metrics
