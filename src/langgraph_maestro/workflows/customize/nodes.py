"""Customize workflow nodes — multi-round LLM interview."""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from langgraph_maestro.core.config import (
    get_models_for_phase,
    load_config,
    workflow_config_path,
)
from langgraph_maestro.core.structured import call_llm_structured

from .schemas import (
    AnswerSynthesis,
    InterviewQuestions,
    WorkflowSpec,
)
from .state import CustomizeState

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = workflow_config_path(__file__)

# Categories every interview must cover
_ALL_CATEGORIES = ("domain", "codebase", "testing", "models", "quality", "workflow")

# Sensible default questions when no LLM is available
_DEFAULT_QUESTIONS: list[dict] = [
    {
        "id": "d1",
        "category": "domain",
        "question": "What domain or industry is this workflow for?",
        "why": "Helps tailor terminology and examples.",
        "examples": ["healthcare", "fintech", "e-commerce"],
    },
    {
        "id": "c1",
        "category": "codebase",
        "question": "What programming languages and frameworks does your codebase use?",
        "why": "Determines which linters and formatters to wire up.",
        "examples": ["Python/FastAPI", "TypeScript/Next.js", "Swift/SwiftUI"],
    },
    {
        "id": "t1",
        "category": "testing",
        "question": "What testing frameworks and CI systems do you use?",
        "why": "Ensures generated tests are compatible with your stack.",
        "examples": ["pytest + GitHub Actions", "Jest + CircleCI"],
    },
    {
        "id": "m1",
        "category": "models",
        "question": "Which LLM models do you want the workflow to use?",
        "why": "Sets up the model fallback chain.",
        "examples": ["claude-sonnet-4-6", "gpt-4o", "local llama"],
    },
    {
        "id": "q1",
        "category": "quality",
        "question": "What quality gates matter most to you (type-checking, lint, tests, review)?",
        "why": "Decides which validation phases to enable.",
        "examples": ["mypy strict", "eslint + prettier", "mandatory code review"],
    },
    {
        "id": "w1",
        "category": "workflow",
        "question": "Describe your ideal development workflow from task to merge.",
        "why": "Shapes the overall graph topology.",
        "examples": ["plan -> implement -> test -> review -> merge"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cfg() -> dict[str, Any]:
    """Load the customize workflow config, returning empty dict on failure."""
    try:
        return load_config(_DEFAULT_CONFIG)
    except FileNotFoundError:
        return {}


def _models(phase: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """Get model list for *phase*, falling back to claude-sonnet-4-6."""
    if cfg is None:
        cfg = _load_cfg()
    try:
        return get_models_for_phase(phase, cfg)
    except (ValueError, KeyError):
        return ["claude-sonnet-4-6"]


def _categories_with_data(ctx: dict) -> set[str]:
    """Return the set of categories that have at least one key in gathered_context."""
    found: set[str] = set()
    for cat in _ALL_CATEGORIES:
        if ctx.get(cat) and isinstance(ctx[cat], dict) and len(ctx[cat]) > 0:
            found.add(cat)
    return found


# ---------------------------------------------------------------------------
# 1. interview_node
# ---------------------------------------------------------------------------

def interview_node(state: CustomizeState) -> dict[str, Any]:
    """Generate interview questions.

    First round: broad discovery across all six categories.
    Later rounds: targeted follow-ups based on gaps in gathered_context.
    """
    current_round = state.get("current_round", 0)
    gathered_context = state.get("gathered_context", {})
    interview_history = state.get("interview_history", [])
    cfg = _load_cfg()

    covered = _categories_with_data(gathered_context)
    missing = sorted(set(_ALL_CATEGORIES) - covered)

    if current_round == 0:
        instruction = (
            "Generate 6-8 broad discovery interview questions, at least one per "
            "category: domain, codebase, testing, models, quality, workflow. "
            "The user is customizing a LangGraph-based LLM workflow."
        )
    else:
        instruction = (
            f"We are on interview round {current_round + 1}. "
            f"Categories still lacking data: {missing}. "
            f"Context gathered so far: {gathered_context}. "
            "Generate 3-5 targeted follow-up questions to fill gaps."
        )

    prompt = (
        f"{instruction}\n\n"
        "Return a JSON object matching the InterviewQuestions schema with fields: "
        "questions (list of {{id, category, question, why, examples}}), "
        "reasoning (str), estimated_completeness (float 0-1)."
    )

    try:
        result: InterviewQuestions = call_llm_structured(
            prompt=prompt,
            models=_models("interview", cfg),
            response_model=InterviewQuestions,
            phase="interview",
            config=cfg,
        )
        questions = [q.model_dump() for q in result.questions]
    except Exception:
        logger.warning("interview_node: LLM unavailable, using default questions")
        questions = list(_DEFAULT_QUESTIONS)

    return {
        "current_questions": questions,
        "phase": "interview",
    }


# ---------------------------------------------------------------------------
# 2. collect_answers_node
# ---------------------------------------------------------------------------

def collect_answers_node(state: CustomizeState) -> dict[str, Any]:
    """Collect answers from stdin (CLI) and synthesize into gathered_context."""
    current_questions = state.get("current_questions", [])
    gathered_context = dict(state.get("gathered_context", {}))
    interview_history = list(state.get("interview_history", []))
    current_round = state.get("current_round", 0)
    cfg = _load_cfg()

    is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()

    answers: list[dict[str, str]] = []
    for q in current_questions:
        qtext = q.get("question", "")
        if is_tty:
            print(f"\n[{q.get('category', '?')}] {qtext}")
            if q.get("examples"):
                print(f"  (examples: {', '.join(q['examples'])})")
            answer = input("> ").strip()
        else:
            answer = ""
        answers.append({"question_id": q.get("id", ""), "question": qtext, "answer": answer})

    # Synthesize answers into structured context updates
    answers_text = "\n".join(
        f"Q ({a['question_id']}): {a['question']}\nA: {a['answer'] or '(no answer)'}"
        for a in answers
    )

    synthesis_prompt = (
        f"Synthesize these interview answers into structured updates.\n\n"
        f"{answers_text}\n\n"
        f"Existing context: {gathered_context}\n\n"
        "Return JSON with keys: domain_updates, codebase_updates, testing_updates, "
        "models_updates, quality_updates, workflow_updates. "
        "Each is a dict of key-value pairs to merge."
    )

    try:
        synthesis: AnswerSynthesis = call_llm_structured(
            prompt=synthesis_prompt,
            models=_models("collect", cfg),
            response_model=AnswerSynthesis,
            phase="collect",
            config=cfg,
        )
        for cat in _ALL_CATEGORIES:
            updates = getattr(synthesis, f"{cat}_updates", {})
            if updates:
                if cat not in gathered_context:
                    gathered_context[cat] = {}
                gathered_context[cat].update(updates)
    except Exception:
        logger.warning("collect_answers_node: LLM unavailable, storing raw answers")
        for a in answers:
            if a["answer"]:
                # Find the category from the question
                matching_q = next(
                    (q for q in current_questions if q.get("id") == a["question_id"]),
                    None,
                )
                cat = matching_q.get("category", "domain") if matching_q else "domain"
                if cat not in gathered_context:
                    gathered_context[cat] = {}
                gathered_context[cat][a["question_id"]] = a["answer"]

    interview_history.append({
        "round": current_round,
        "questions": current_questions,
        "answers": answers,
    })

    # Compute confidence based on category coverage
    covered = _categories_with_data(gathered_context)
    confidence = len(covered) / len(_ALL_CATEGORIES)

    return {
        "gathered_context": gathered_context,
        "interview_history": interview_history,
        "current_round": current_round + 1,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# 3. synthesize_node
# ---------------------------------------------------------------------------

def synthesize_node(state: CustomizeState) -> dict[str, Any]:
    """Synthesize gathered_context into a WorkflowSpec."""
    gathered_context = state.get("gathered_context", {})
    cfg = _load_cfg()

    prompt = (
        f"Based on the following gathered context, produce a workflow specification.\n\n"
        f"Context: {gathered_context}\n\n"
        "Return JSON matching WorkflowSpec schema with fields: "
        "workflow_name (str), description (str), "
        "phases (list of {{name, enabled, models}}), "
        "config ({{max_review_rounds, escalation_enabled, timeouts}}), "
        "prompt_overrides (dict of phase->prompt)."
    )

    try:
        spec: WorkflowSpec = call_llm_structured(
            prompt=prompt,
            models=_models("synthesize", cfg),
            response_model=WorkflowSpec,
            phase="synthesize",
            config=cfg,
        )
        workflow_spec = spec.model_dump()
    except Exception:
        logger.warning("synthesize_node: LLM unavailable, using defaults from context")
        wf_name = gathered_context.get("domain", {}).get("name", "custom_workflow")
        workflow_spec = WorkflowSpec(
            workflow_name=wf_name or "custom_workflow",
            description="Auto-generated workflow",
            phases=[
                {"name": "plan", "enabled": True, "models": ["claude-sonnet-4-6"]},
                {"name": "execute", "enabled": True, "models": ["claude-sonnet-4-6"]},
                {"name": "review", "enabled": True, "models": ["claude-sonnet-4-6"]},
            ],
        ).model_dump()

    # Build a domain profile summary
    domain_profile = {
        "categories_covered": sorted(_categories_with_data(gathered_context)),
        "context_snapshot": gathered_context,
    }

    return {
        "workflow_spec": workflow_spec,
        "domain_profile": domain_profile,
    }


# ---------------------------------------------------------------------------
# 4. generate_node
# ---------------------------------------------------------------------------

def generate_node(state: CustomizeState) -> dict[str, Any]:
    """Generate workflow files from workflow_spec using scaffold_workflow."""
    from langgraph_maestro.templates import scaffold_workflow

    workflow_spec = state.get("workflow_spec", {})
    target_dir = state.get("target_dir", "")

    wf_name = workflow_spec.get("workflow_name", "custom_workflow")
    description = workflow_spec.get("description", "")
    phases = workflow_spec.get("phases", [])
    default_model = "claude-sonnet-4-6"
    if phases:
        first_models = phases[0].get("models", [])
        if first_models:
            default_model = first_models[0]

    # Use a temporary directory for scaffolding, then read files into memory
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        scaffold_workflow(
            target_dir=tmpdir,
            workflow_name=wf_name,
            description=description,
            default_model=default_model,
        )

        generated_files: dict[str, str] = {}
        for p in Path(tmpdir).rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(tmpdir))
                generated_files[rel] = p.read_text(encoding="utf-8")

    # Apply customizations from workflow_spec
    # Override config.yaml with spec phases and config
    config_content = {
        "workflow": wf_name,
        "description": description,
        "phases": {},
        "timeouts": workflow_spec.get("config", {}).get("timeouts", {"default": 300}),
    }
    for phase in phases:
        if phase.get("enabled", True):
            config_content["phases"][phase["name"]] = phase.get(
                "models", [default_model]
            )
    generated_files["config.yaml"] = yaml.dump(
        config_content, default_flow_style=False, sort_keys=False
    )

    # Apply prompt overrides as a separate prompts.yaml
    prompt_overrides = workflow_spec.get("prompt_overrides", {})
    if prompt_overrides:
        generated_files["prompts.yaml"] = yaml.dump(
            prompt_overrides, default_flow_style=False, sort_keys=False
        )

    return {"generated_files": generated_files}


# ---------------------------------------------------------------------------
# 5. validate_node
# ---------------------------------------------------------------------------

def validate_node(state: CustomizeState) -> dict[str, Any]:
    """Validate generated files: ast.parse() for .py, yaml.safe_load() for .yaml."""
    generated_files = state.get("generated_files", {})
    validation_attempts = state.get("validation_attempts", 0)
    errors: list[str] = []

    for filename, content in generated_files.items():
        if filename.endswith(".py"):
            try:
                ast.parse(content, filename=filename)
            except SyntaxError as exc:
                errors.append(f"{filename}: SyntaxError at line {exc.lineno}: {exc.msg}")
        elif filename.endswith(".yaml") or filename.endswith(".yml"):
            try:
                yaml.safe_load(content)
            except yaml.YAMLError as exc:
                errors.append(f"{filename}: YAML error: {exc}")

    if errors:
        logger.warning("validate_node: %d error(s) found", len(errors))

    return {
        "validation_errors": errors,
        "validation_attempts": validation_attempts + 1,
    }


# ---------------------------------------------------------------------------
# 6. write_output_node
# ---------------------------------------------------------------------------

def write_output_node(state: CustomizeState) -> dict[str, Any]:
    """Write generated_files to target_dir and produce a summary."""
    generated_files = state.get("generated_files", {})
    target_dir = state.get("target_dir", "")
    validation_errors = state.get("validation_errors", [])

    if not target_dir:
        target_dir = str(Path.cwd() / "generated_workflow")

    out = Path(target_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for filename, content in generated_files.items():
        dest = out / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(str(dest))

    warnings = ""
    if validation_errors:
        warnings = (
            "\n\nWarnings (validation errors present but writing anyway):\n"
            + "\n".join(f"  - {e}" for e in validation_errors)
        )

    summary = (
        f"Wrote {len(written)} file(s) to {out}:\n"
        + "\n".join(f"  - {w}" for w in written)
        + warnings
    )

    return {
        "output_dir": str(out),
        "final_summary": summary,
    }
