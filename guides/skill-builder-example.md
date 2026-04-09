# Example: Skill Builder Output for a Python Web API

This shows what the skill-builder produces when pointed at a hypothetical FastAPI project called `acme-api`.

---

## Phase 1 Output: Codebase Analysis

```markdown
## Codebase Analysis: acme-api

**Domain**: Web app (backend API)
**Languages**: Python 95%, SQL 3%, Shell 2%
**Build**: pyproject.toml + uv, Docker for production
**Tests**: pytest with httpx.AsyncClient, 78% coverage
**Existing AI config**: None

### Key Patterns
- FastAPI with SQLAlchemy async, Alembic migrations
- Pydantic v2 models in `schemas/`, SQLAlchemy models in `models/`
- Background tasks via Celery + Redis
- Auth via JWT with role-based access (admin, user, viewer)
- All endpoints return `ApiResponse` wrapper with error codes from `core/errors.py`

### Pain Points / Automation Candidates
- Migration reviews: Every migration needs manual review for data loss, index impact,
  and rollback safety. Happens 3-4 times per week.
- Endpoint scaffolding: New CRUD endpoints follow an identical pattern (router, schema,
  service, tests) but are written by hand each time.
- Dependency upgrades: Monthly dependency bumps break things in non-obvious ways.

### Domain-Specific Constraints
- All database queries must go through the service layer (no direct ORM in routes)
- Celery tasks must be idempotent (retries are automatic)
- JWT tokens include `org_id` for multi-tenant isolation -- every query must filter by it
```

---

## Phase 2 Output: Proposals

### Migration Reviewer (Workflow)
**Type**: Workflow (based on `examples/pr_review/`)
**Why**: Migrations are the highest-risk changes and happen 3-4x/week. Automated review catches data loss, missing rollbacks, and index issues before human review.
**Sketch**: Fan-out reviewers check: (1) reversibility, (2) data preservation, (3) index/performance impact, (4) multi-tenant safety. Synthesize into pass/fail with specific findings.
**Priority**: High

### Endpoint Scaffolder (Workflow)
**Type**: Workflow (based on `examples/adaptive/`)
**Why**: CRUD endpoint creation is the most repetitive task -- same pattern every time but easy to miss the auth decorator or tenant filter.
**Sketch**: Think (parse the resource spec) -> Plan (list files to create) -> Act (generate router, schema, service, test files) -> Verify (run pytest, check all conventions).
**Priority**: High

### FastAPI Domain Expert (Agent Role)
**Type**: Agent Role
**Why**: Every AI interaction with this codebase needs to know about the ApiResponse wrapper, service layer rule, and multi-tenant JWT filtering. Loading this as context prevents the most common mistakes.
**Sketch**: Covers the service layer pattern, ApiResponse format, JWT/org_id filtering requirement, Celery idempotency rule, and lists the "never do this" anti-patterns.
**Priority**: High

### Data Model Reference (Domain Context)
**Type**: Domain Context File
**Why**: Agents working on migrations or new endpoints need to understand the schema relationships without reading every model file.
**Sketch**: Entity-relationship summary, key foreign keys, soft-delete conventions, audit column patterns, multi-tenant org_id requirement.
**Priority**: Medium

---

## Phase 3 Output: Sample Generated Workflow

### Migration Reviewer -- `workflows/migration_review/`

**prompts/analyze_reversibility.txt**:
```markdown
# Migration Reversibility Check

Review this Alembic migration for reversibility.

## Migration
{migration_content}

## Check these:
1. Does the `downgrade()` function exist and is it non-empty?
2. Can the downgrade run without data loss?
3. Are there any `op.drop_column()` or `op.drop_table()` calls in upgrade
   that would lose data? If so, does downgrade recreate them?
4. Are there any `op.execute()` raw SQL statements that lack a corresponding
   downgrade statement?

## Response format
Respond with JSON:
{
  "reversible": true/false,
  "issues": ["issue 1", "issue 2"],
  "severity": "pass" | "warning" | "blocking"
}
```

**nodes.py** (excerpt):
```python
DEFAULT_MODELS = ["claude-sonnet-4-6"]
_PROMPTS = Path(__file__).parent / "prompts"

def analyze_reversibility(state: dict) -> dict:
    migration = state.get("migration_content", "")
    prompt = (_PROMPTS / "analyze_reversibility.txt").read_text().format(
        migration_content=migration,
    )
    result = call_llm_with_fallback(prompt, DEFAULT_MODELS, phase="reversibility")
    parsed = extract_json(result.get("content", ""))
    return {
        "reversibility_check": parsed or {"reversible": False, "issues": ["parse failure"]},
        "phase": "reversibility",
    }
```

**graph.py** (excerpt):
```python
def build_graph():
    graph = StateGraph(MigrationReviewState)
    graph.add_node("analyze_reversibility", analyze_reversibility)
    graph.add_node("analyze_data_safety", analyze_data_safety)
    graph.add_node("analyze_performance", analyze_performance)
    graph.add_node("analyze_tenant_safety", analyze_tenant_safety)
    graph.add_node("synthesize", synthesize_findings)

    graph.set_entry_point("analyze_reversibility")
    # Fan-out: all analyzers run, then synthesize
    graph.add_edge("analyze_reversibility", "analyze_data_safety")
    graph.add_edge("analyze_data_safety", "analyze_performance")
    graph.add_edge("analyze_performance", "analyze_tenant_safety")
    graph.add_edge("analyze_tenant_safety", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile(checkpointer=get_checkpointer())
```

### FastAPI Domain Expert -- `roles/fastapi-expert.md`

```markdown
# FastAPI Domain Expert -- acme-api

You are a backend engineer specializing in the acme-api codebase.

## Your Responsibility
Review and write FastAPI code that follows acme-api conventions.

## Domain Knowledge
- All endpoints return `ApiResponse` from `core/responses.py`
- Database access goes through service layer (`services/`) -- never call
  SQLAlchemy directly in route handlers
- JWT tokens contain `org_id` -- every database query MUST filter by
  `org_id=current_user.org_id` for multi-tenant isolation
- Celery tasks in `tasks/` must be idempotent (automatic retries are enabled)
- Pydantic schemas live in `schemas/`, SQLAlchemy models in `models/`

## Conventions
- Route files: `routes/{resource}.py`, one router per resource
- Service files: `services/{resource}.py`, async methods, raise `ApiError` on failure
- Test files: `tests/test_{resource}.py`, use `async_client` fixture

## What NOT to Do
- Do NOT import SQLAlchemy models in route files -- use the service layer
- Do NOT return raw dicts from endpoints -- always use `ApiResponse`
- Do NOT forget `org_id` filtering -- this is a multi-tenant system
- Do NOT make Celery tasks that fail differently on retry -- they must be idempotent
```

---

## What This Demonstrates

1. **Analysis is specific** -- it names actual patterns, files, and pain points, not generic observations.
2. **Proposals are prioritized** -- the user sees what matters most and can choose.
3. **Generated files follow maestro conventions** -- Python constants for models, markdown prompts with placeholders, `extract_json()` for parsing, self-contained workflow directories.
4. **Agent roles capture what models don't know** -- the multi-tenant filtering rule, the service layer convention, the specific anti-patterns that cause bugs in this codebase.
5. **Everything is plain files** -- no framework config, no proprietary formats. Works with any AI tool.
