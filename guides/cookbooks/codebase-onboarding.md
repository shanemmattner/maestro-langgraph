# Codebase Onboarding

A step-by-step playbook for getting up to speed on an unfamiliar codebase. Produces a structured summary that serves as context for all future work.

**When to use:** First time working with a repo, onboarding a new agent to a project, or when you need to understand a codebase before the skill-builder (see `guides/skill-builder.md`) can propose workflows.

**Principle:** Maestro #6 -- "Write, select, compress, and isolate context deliberately."

---

## Prerequisites

- Access to the repository (local clone or remote)
- Ability to read files and run basic commands (`ls`, `cat`, build/test commands)

---

## Steps

### 1. Read the top-level documentation

Start with the files that explain intent and conventions. Read them in this order:

| File | What it tells you |
|------|------------------|
| `README.md` | Purpose, setup instructions, high-level architecture |
| `CLAUDE.md` | AI-specific instructions, hard rules, conventions |
| `AGENTS.md` | Agent roles and delegation patterns |
| `.cursorrules` | Cursor-specific conventions (often similar to CLAUDE.md) |
| `CONTRIBUTING.md` | How the team expects contributions to work |
| `CHANGELOG.md` | Recent changes, release cadence |

Not every repo has all of these. Read what exists and skip what does not.

### 2. Map the directory structure

List the top-level directories and identify their purpose. For each directory, write one sentence describing what it contains.

```
src/           -- Application source code
tests/         -- Test suite (mirrors src/ structure)
docs/          -- Documentation and ADRs
scripts/       -- Build, deploy, and utility scripts
migrations/    -- Database schema migrations
config/        -- Environment and service configuration
```

Go one level deeper into `src/` (or equivalent) to understand the module breakdown.

### 3. Identify the tech stack

Find and read the dependency manifest:

| File | Ecosystem |
|------|-----------|
| `package.json` | Node.js / JavaScript / TypeScript |
| `pyproject.toml` or `requirements.txt` | Python |
| `Cargo.toml` | Rust |
| `go.mod` | Go |
| `Gemfile` | Ruby |
| `Package.swift` or `*.xcodeproj` | Swift / Apple |
| `build.gradle` | JVM / Kotlin / Java |

Note the key dependencies -- frameworks, ORMs, test runners, linters. These tell you more about the architecture than the source code often does.

### 4. Find the entry points

Every codebase has a small number of places where execution starts. Find them:

- **CLI**: Look for `main()`, `if __name__ == "__main__"`, `bin/` scripts, or argparse/click/cobra definitions
- **API server**: Look for route definitions, `app.py`, `server.ts`, controller directories
- **Library**: Look for the public API surface -- `__init__.py`, `index.ts`, `lib.rs`
- **Workflows**: Look for `run.py`, `graph.py`, DAG definitions, or pipeline configs

Trace one request or command from entry point through to completion. This gives you the execution flow.

### 5. Read the test structure

Tests reveal what the team considers important and how they verify correctness.

- Where do tests live? (`tests/`, `__tests__/`, `*_test.go`, `spec/`)
- What framework? (pytest, jest, XCTest, go test)
- What is the unit vs integration vs E2E split?
- Are there test fixtures, factories, or helpers?
- How are tests run? (`npm test`, `pytest`, `make test`, CI scripts)

Run the test suite once to see if it passes. A failing test suite is important context.

### 6. Identify coding conventions

Read 3-4 representative source files and note:

- **Naming**: camelCase vs snake_case, prefix conventions, file naming
- **Error handling**: Exceptions, Result types, error codes, custom error classes
- **Logging**: `print()` vs structured logging, log levels, logger setup
- **Imports**: Absolute vs relative, grouping conventions, barrel files
- **Comments**: Docstrings, inline comments, ADR references

Also check for automated enforcement: `.eslintrc`, `ruff.toml`, `.editorconfig`, pre-commit hooks, CI lint steps.

### 7. Produce the summary

Write a structured summary document. This becomes the reference for all future work in this codebase.

```markdown
## Codebase Summary: [repo-name]

**Purpose**: [One sentence]
**Languages**: [List with approximate percentages]
**Framework**: [Primary framework]
**Build system**: [How to build]
**Test command**: [How to run tests]

### Directory Map
- `dir/` -- [purpose]

### Key Dependencies
- [dependency] -- [what it is used for]

### Entry Points
- [file] -- [what it starts]

### Conventions
- [convention 1]
- [convention 2]

### Things to Watch Out For
- [gotcha 1]
- [gotcha 2]
```

---

## Expected Output

A codebase summary document (under 100 lines) that gives any agent or developer enough context to start working without asking basic questions about where things are or how things work.

---

## Anti-patterns

- **Reading every file**: You do not need to read the entire codebase. Read the structure, the docs, the entry points, and a few representative files.
- **Skipping tests**: The test structure tells you what matters. Ignoring it means missing the team's quality expectations.
- **Assuming conventions**: Do not assume snake_case or camelCase -- check. Do not assume pytest -- check. Conventions vary and getting them wrong creates friction.
- **No written output**: If the onboarding lives only in your context window, it is lost when the session ends. Write it down.
