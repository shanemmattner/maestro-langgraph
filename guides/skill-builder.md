# Skill Builder

A meta-skill that analyzes a codebase and helps users create custom workflows, agent prompts, and domain context files tailored to that codebase. Works with any AI coding tool (Claude Code, Codex, Cursor, Windsurf, etc.).

**When to use:** You have a codebase and want to set up AI-assisted development workflows for it -- custom agent roles, LangGraph workflows, domain knowledge files, and per-repo config.

## How It Works

Four phases, each requiring user input before proceeding:

```
Analyze codebase -> Propose skills/workflows -> Get feedback -> Generate files -> Review
```

Never skip the feedback step. The user knows their codebase better than you do.

---

## Phase 1: Analyze the Target Codebase

Read the repo and build a mental model. Run these steps in parallel where possible.

### 1.1 Repository Structure

Explore the directory tree, language breakdown, and key files:

```
- List top-level directories and their purposes
- Identify primary language(s) and framework(s)
- Find the build system (Makefile, package.json, pyproject.toml, Cargo.toml, etc.)
- Find the test setup (pytest, jest, XCTest, etc.)
- Count approximate lines of code per language
```

### 1.2 Existing AI Config

Check for existing AI tool configuration -- these tell you what's already been set up:

```
- CLAUDE.md, .claude/ directory
- AGENTS.md
- .cursorrules, .cursor/ directory
- .github/copilot-instructions.md
- .aider*, .continue/ directory
- Any custom prompt files or agent configs
```

If existing config exists, read it carefully. The goal is to enhance, not duplicate.

### 1.3 Domain Identification

Classify the project. This drives which workflows and agent roles make sense:

| Domain | Signals | Likely Workflows |
|--------|---------|-----------------|
| Web app (frontend) | React/Vue/Svelte, components/, pages/ | UI review, accessibility audit, component gen |
| Web app (backend) | routes/, controllers/, models/, migrations/ | API review, schema changes, endpoint gen |
| Mobile app | Xcode project, Android manifests, Flutter | Platform-specific review, build scripts |
| ML pipeline | training/, models/, datasets/, notebooks | Experiment tracking, model eval, data validation |
| CLI tool | argparse/clap/cobra, main entry point | Command testing, help text review |
| Library/SDK | public API surface, docs/, examples/ | API design review, breaking change detection |
| Monorepo | Multiple packages/apps, workspace config | Cross-package impact analysis |
| Infrastructure | Terraform, Docker, k8s manifests | Drift detection, security review |

### 1.4 Pattern Recognition

Identify the team's conventions and pain points:

- **Coding conventions**: Naming, formatting, import style, error handling patterns
- **Testing approach**: Unit/integration/E2E split, coverage expectations, test utilities
- **CI/CD**: What runs on every PR? What gates deployment?
- **Deployment**: How does code get to production?
- **Documentation**: Where do decisions live? ADRs, wiki, inline comments?
- **Repetitive tasks**: What does the team do over and over? (These are workflow candidates)

### 1.5 Output

Write a concise analysis summary. Format:

```markdown
## Codebase Analysis: [repo-name]

**Domain**: [classification]
**Languages**: [list with approximate %]
**Build**: [system]
**Tests**: [framework + approach]
**Existing AI config**: [what exists, if anything]

### Key Patterns
- [pattern 1]
- [pattern 2]

### Pain Points / Automation Candidates
- [candidate 1]: [why it's repetitive or error-prone]
- [candidate 2]: [why]

### Domain-Specific Constraints
- [constraint 1]: [why it matters for AI workflows]
```

Present this to the user and ask: "Does this match your understanding? What did I miss? What are the biggest pain points you'd want AI help with?"

---

## Phase 2: Propose Skills and Workflows

Based on the analysis and user feedback, propose concrete artifacts. Each proposal needs three things: what it is, why it's useful for this specific repo, and a brief sketch.

### 2.1 Workflows

Map repetitive tasks to maestro workflow patterns:

| Maestro Pattern | Source | Best For |
|----------------|--------|----------|
| think -> plan -> adversarial review -> act -> verify | `examples/adaptive/` | Features, refactors, bug fixes |
| fan-out -> analyze -> synthesize | `examples/pr_review/` | Code review, audit, analysis |
| think -> reason -> conclude | `examples/chain_of_thought/` | Design decisions, investigation |

For each proposed workflow:
- Name it descriptively (e.g., `api-endpoint-builder`, `migration-reviewer`)
- Identify which maestro example to start from
- List the customizations needed (prompt changes, extra nodes, domain tools)
- Specify which phases need domain-specific prompts

### 2.2 Agent Roles

Propose specialized agent role prompts. Good agent roles are:
- Scoped to one responsibility (maestro principle #2)
- Loaded with domain knowledge the model wouldn't otherwise have
- Specific about what NOT to do (anti-patterns from this codebase)

Example proposals:
```
- "Django Migration Reviewer" -- knows the ORM quirks, checks for data migrations,
  flags irreversible operations. Loaded as context for PR review workflows.
- "React Component Author" -- knows the design system tokens, accessibility
  requirements, and testing patterns. Used in the adaptive workflow's act phase.
```

### 2.3 Domain Context Files

Propose markdown files that capture domain knowledge for AI consumption:
- Architecture overview (for agents that need to understand the system)
- API contracts (for agents that generate or modify endpoints)
- Data model reference (for agents working with the database)
- Testing guide (for agents that write or review tests)

These follow maestro principle #6 (Context Engineering) -- write context that agents can load just-in-time.

### 2.4 Tool Integrations

Recommend which maestro tools would be useful:

| Tool | When to Recommend |
|------|------------------|
| `web.py` (SearXNG + Crawl4AI) | Projects with external dependencies, API integrations |
| `verify.py` | Any project with automated tests |
| `tracing.py` (Langfuse) | Teams that want to observe and improve workflows over time |
| `eval.py` (LLM-as-judge) | Projects where output quality is subjective (docs, UX copy) |
| `budget.py` | Teams concerned about LLM costs |
| `stall.py` | Complex workflows with retry loops |

### 2.5 Output

Present all proposals in a single document. For each item:

```markdown
### [Proposal Name]
**Type**: Workflow / Agent Role / Domain Context / Tool Integration
**Why**: [One sentence on why this is useful for THIS repo specifically]
**Sketch**: [3-5 lines describing what the artifact would contain]
**Priority**: High / Medium / Low
```

Ask the user: "Which of these would you like me to generate? Any modifications?"

---

## Phase 3: Generate Files

After user approval, generate the artifacts. Follow these conventions.

### 3.1 Workflow Files

Each workflow is a self-contained directory:

```
workflows/[name]/
  graph.py       # LangGraph StateGraph definition
  nodes.py       # Node functions (one task per node)
  state.py       # TypedDict state schema
  prompts/       # Markdown prompt templates
    think.txt
    plan.txt
    act.txt
    verify.txt
  run.py         # Entry point
```

Key rules from maestro:
- Models are Python constants, not config files: `DEFAULT_MODELS = ["claude-sonnet-4-6"]`
- Nodes use `call_llm_with_fallback()` + `extract_json()` for permissive parsing
- Prompts are markdown files with `{variable}` placeholders
- Each node returns a partial state update dict
- Route functions are pure functions on state

### 3.2 Agent Role Prompts

Markdown files that can be loaded as system context by any AI tool:

```markdown
# [Role Name]

You are a [role] for the [project-name] codebase.

## Your Responsibility
[One focused task]

## Domain Knowledge
[Specific facts about this codebase the model needs]

## Conventions
[Coding patterns, naming rules, anti-patterns to avoid]

## What NOT to Do
[Specific mistakes that are easy to make in this codebase]
```

### 3.3 Per-Repo Config Files

Generate the appropriate config for the user's AI tool:

| Tool | Config File | Notes |
|------|------------|-------|
| Claude Code | `CLAUDE.md` | Project instructions, monorepo structure, hard rules |
| Cursor | `.cursorrules` | Similar content, Cursor-specific formatting |
| Codex | `AGENTS.md` | Agent instructions for OpenAI Codex |
| Generic | `AI_CONTEXT.md` | Tool-agnostic, works as manual reference |

The config file should include:
- Project overview and domain
- Directory structure with purposes
- Coding conventions and anti-patterns
- Testing commands and expectations
- Build/deploy commands
- Links to domain context files and agent role prompts

### 3.4 Domain Context Files

Place in a discoverable location (`docs/ai/`, `.claude/context/`, or alongside the config file). Keep each file focused on one topic and under 200 lines -- agents load them just-in-time, not all at once.

---

## Phase 4: Multi-Model Review

After generation, recommend this review pattern:

1. **Fast model generates** (Sonnet, Codex, GPT-4o) -- handles the bulk of file creation
2. **Thorough model reviews** (Opus, o3) -- checks for:
   - Accuracy: Do the prompts reflect actual codebase patterns?
   - Completeness: Are there obvious workflows or roles missing?
   - Anti-patterns: Does anything contradict maestro principles?
   - Specificity: Is anything too generic to be useful?
3. **User makes final call** -- the human knows the codebase best

Present the review findings and let the user decide what to keep, modify, or discard.

---

## Principles to Follow

These come from the maestro repo and should guide every decision:

1. **Start simple.** Propose the minimum viable set of workflows. The user can always add more.
2. **One agent, one task.** Each agent role does one thing. Don't create mega-prompts.
3. **Specificity over generality.** "Use our `ApiError` class with error codes from `errors.py`" beats "handle errors properly."
4. **Dead ends are valuable.** If you discover something that won't work for this codebase, document it.
5. **Markdown prompts are the product.** The quality of the generated prompts determines the quality of the AI assistance. Invest time here.
6. **No framework lock-in.** Everything generated should be plain files (Python, Markdown) that work with any tool. No proprietary config formats.
7. **Context engineering.** Write context files that give agents exactly what they need -- no more, no less.

---

## Quick Reference

| Phase | Input | Output | User Action |
|-------|-------|--------|-------------|
| Analyze | Repo path | Codebase summary | Confirm / correct |
| Propose | Analysis + feedback | Prioritized proposals | Select / modify |
| Generate | Approved proposals | Files on disk | Review |
| Review | Generated files | Review findings | Accept / revise |
