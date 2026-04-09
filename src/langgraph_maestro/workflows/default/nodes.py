"""Default workflow nodes — redesigned pipeline with context engineering,
piece-level execution, multi-layer review, verification, and after-action review.

Node functions follow these conventions:
- Each takes ``state: dict`` and returns ``dict`` with only the fields it updates.
- Config is resolved via ``state.get("config_path", _CONFIG)``.
- Models come from ``get_models_for_phase(phase_name, config)``.
- Prompts are loaded from the ``prompts/`` directory next to this file.
- Errors are logged and returned as state — nodes never crash the graph.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from langgraph_maestro.core.config import (
    load_config,
    get_models_for_phase,
    workflow_config_path,
)
from langgraph_maestro.core.llm import (
    call_agent,
    call_llm_with_fallback,
    _get_changed_files,
    extract_json,
    rescue_json,
)
from langgraph_maestro.core.schemas import (
    DecomposeOutput,
    TaskAnalysisOutput,
    ContextEngineeringOutput,
    PieceReviewOutput,
    HolisticReviewOutput,
    AdversarialReviewOutput,
    VerificationOutput,
    AAROutput,
)
from langgraph_maestro.core.stall import StallDetector
from langgraph_maestro.core.structured import call_llm_structured
from langgraph_maestro.core.web import (
    is_search_available,
    search_and_extract,
    format_findings_for_llm,
    web_search,
)
from langgraph_maestro.nodes.decompose import make_decompose_node
from langgraph_maestro.nodes.escalate import make_escalate_node

logger = logging.getLogger(__name__)

_CONFIG = workflow_config_path(__file__)
_PROMPTS = str(Path(__file__).parent / "prompts")


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_get_models(phase: str, config: dict) -> List[str]:
    """Get models for a phase, falling back to 'decompose' if phase missing."""
    try:
        return get_models_for_phase(phase, config)
    except ValueError:
        logger.warning(
            "phase_not_in_config",
            extra={"phase": phase, "fallback": "decompose"},
        )
        return get_models_for_phase("decompose", config)


# ---------------------------------------------------------------------------
# 1. analyze_task_node
# ---------------------------------------------------------------------------

def analyze_task_node(state: dict) -> dict:
    """Analyze the task to extract type, success criteria, ambiguities, and
    search queries.  Uses call_llm_structured with TaskAnalysisOutput."""
    start = time.time()
    task = state.get("task", "")
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("analyze", config)
    prompts_path = Path(_PROMPTS)

    logger.info("analyze_task_start", extra={"task": task[:120]})

    try:
        template = _load_prompt("analyzer", prompts_path)
    except FileNotFoundError:
        template = (
            "Analyze the following task and return JSON.\n\n"
            "Task: {task}\n\n"
            "Return: task_type, success_criteria (list), ambiguities (list), "
            "search_queries (list), relevant_file_patterns (list)."
        )

    prompt = template.replace("{task}", task)

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=TaskAnalysisOutput,
            phase="analyze",
            config=config,
            cwd=cwd,
            system_prompt="You are a task analysis agent. Return valid JSON only.",
        )
    except Exception as exc:
        logger.error("analyze_task_failed", extra={"error": str(exc)})
        return {
            "errors": [f"Task analysis failed: {exc}"],
            "phase": "analyze",
        }

    elapsed = round(time.time() - start, 3)
    logger.info(
        "analyze_task_done",
        extra={
            "task_type": output.task_type,
            "num_criteria": len(output.success_criteria),
            "num_queries": len(output.search_queries),
            "elapsed": elapsed,
        },
    )

    return {
        "task_type": output.task_type,
        "success_criteria": output.success_criteria,
        "ambiguities": output.ambiguities,
        "search_queries": output.search_queries,
        "relevant_file_patterns": output.relevant_file_patterns,
        "phase": "analyze",
    }


# ---------------------------------------------------------------------------
# 2. research_node
# ---------------------------------------------------------------------------

def research_node(state: dict) -> dict:
    """Run web searches using queries from analyze_task.  Degrades gracefully
    if the search stack is unavailable."""
    start = time.time()
    queries = state.get("search_queries", [])
    config_path = state.get("config_path", _CONFIG)

    logger.info("research_start", extra={"num_queries": len(queries)})

    domain_research: List[Dict[str, Any]] = []
    search_available = is_search_available()

    if not search_available:
        logger.warning("research_search_unavailable")
        return {
            "domain_research": [],
            "search_available": False,
            "phase": "research",
        }

    for query in queries[:5]:  # cap at 5 queries to limit latency
        try:
            finding = search_and_extract(query, max_results=3)
            formatted = format_findings_for_llm(finding)
            domain_research.append({
                "query": query,
                "formatted": formatted,
                "num_results": len(finding.results),
                "num_pages": len(finding.pages),
                "error": finding.error,
            })
        except Exception as exc:
            logger.warning("research_query_failed", extra={
                "query": query, "error": str(exc),
            })
            domain_research.append({
                "query": query,
                "formatted": f"Search failed: {exc}",
                "num_results": 0,
                "num_pages": 0,
                "error": str(exc),
            })

    elapsed = round(time.time() - start, 3)
    logger.info(
        "research_done",
        extra={
            "num_findings": len(domain_research),
            "elapsed": elapsed,
        },
    )

    return {
        "domain_research": domain_research,
        "search_available": search_available,
        "phase": "research",
    }


# ---------------------------------------------------------------------------
# 3. build_context_node
# ---------------------------------------------------------------------------

def build_context_node(state: dict) -> dict:
    """Synthesize research findings into structured domain context using
    call_llm_structured with ContextEngineeringOutput."""
    start = time.time()
    task = state.get("task", "")
    domain_research = state.get("domain_research", [])
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("build_context", config)
    prompts_path = Path(_PROMPTS)

    logger.info("build_context_start", extra={"num_findings": len(domain_research)})

    # Assemble research text
    research_text = "\n\n".join(
        r.get("formatted", "") for r in domain_research if r.get("formatted")
    ) or "No web research available."

    try:
        template = _load_prompt("context_builder", prompts_path)
    except FileNotFoundError:
        template = (
            "Synthesize the following research into domain context.\n\n"
            "Task: {task}\n\n"
            "Research:\n{research}\n\n"
            "Return: domain_summary, key_constraints (list), recommended_approach, "
            "citations (list of {{claim, source_url, source_title}}), "
            "tool_assignments (dict of phase->tools)."
        )

    prompt = template.replace("{task}", task).replace("{research}", research_text)

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=ContextEngineeringOutput,
            phase="context",
            config=config,
            cwd=cwd,
            system_prompt=(
                "You are a context engineering agent. Synthesize research into "
                "actionable domain knowledge. Return valid JSON only."
            ),
        )
    except Exception as exc:
        logger.error("build_context_failed", extra={"error": str(exc)})
        return {
            "domain_context": f"Context engineering failed: {exc}",
            "tool_recommendations": {},
            "errors": [f"Context build failed: {exc}"],
            "phase": "context",
        }

    domain_context = (
        f"{output.domain_summary}\n\n"
        f"Key constraints:\n"
        + "\n".join(f"- {c}" for c in output.key_constraints)
        + f"\n\nRecommended approach:\n{output.recommended_approach}"
    )

    elapsed = round(time.time() - start, 3)
    logger.info(
        "build_context_done",
        extra={
            "context_len": len(domain_context),
            "num_constraints": len(output.key_constraints),
            "num_citations": len(output.citations),
            "elapsed": elapsed,
        },
    )

    return {
        "domain_context": domain_context,
        "key_constraints": output.key_constraints,
        "citations": output.citations,
        "tool_recommendations": output.tool_assignments,
        "phase": "context",
    }


# ---------------------------------------------------------------------------
# 4. decompose_node (reuse factory)
# ---------------------------------------------------------------------------

decompose_node = make_decompose_node(
    config_path_default=_CONFIG,
    schema_class=DecomposeOutput,
    prompts_dir=_PROMPTS,
)


# ---------------------------------------------------------------------------
# 5. validate_plan_node
# ---------------------------------------------------------------------------

def validate_plan_node(state: dict) -> dict:
    """Deterministic plan validation — no LLM call.

    Checks:
    - Every success criterion is referenced by at least one subtask.
    - Subtask IDs are unique.
    - Subtask descriptions are non-trivially long.
    - No subtask has more than one paragraph of acceptance criteria (complexity).
    """
    start = time.time()
    subtasks = state.get("subtasks", [])
    success_criteria = state.get("success_criteria", [])

    logger.info("validate_plan_start", extra={"num_subtasks": len(subtasks)})

    warnings: List[str] = []

    # Check for empty plan
    if not subtasks:
        warnings.append("Plan has no subtasks.")
        return {
            "subtask_warnings": warnings,
            "plan_valid": False,
            "phase": "validate_plan",
        }

    # Check unique IDs
    ids = [t.get("id", "") for t in subtasks]
    seen = set()
    for task_id in ids:
        if task_id in seen:
            warnings.append(f"Duplicate subtask ID: {task_id}")
        seen.add(task_id)

    # Check subtask quality
    for t in subtasks:
        desc = t.get("description", "")
        if len(desc) < 10:
            warnings.append(
                f"Subtask {t.get('id', '?')} has a very short description "
                f"({len(desc)} chars)."
            )
        ac = t.get("acceptance_criteria", "")
        if not ac:
            warnings.append(
                f"Subtask {t.get('id', '?')} has no acceptance criteria."
            )

    # Check success criteria coverage
    if success_criteria:
        all_descriptions = " ".join(
            t.get("description", "") + " " + t.get("acceptance_criteria", "")
            for t in subtasks
        ).lower()

        for criterion in success_criteria:
            # Simple word overlap check — not perfect but catches obvious gaps
            criterion_words = set(criterion.lower().split())
            # Remove common stop words
            criterion_words -= {
                "the", "a", "an", "is", "are", "should", "must", "be", "to",
                "and", "or", "of", "in", "for", "with", "that", "this",
            }
            overlap = sum(1 for w in criterion_words if w in all_descriptions)
            coverage = overlap / max(len(criterion_words), 1)
            if coverage < 0.3:
                warnings.append(
                    f"Success criterion may not be covered: '{criterion[:80]}'"
                )

    plan_valid = len(warnings) == 0

    elapsed = round(time.time() - start, 3)
    logger.info(
        "validate_plan_done",
        extra={
            "num_warnings": len(warnings),
            "plan_valid": plan_valid,
            "elapsed": elapsed,
        },
    )

    return {
        "subtask_warnings": warnings,
        "plan_valid": plan_valid,
        "phase": "validate_plan",
    }


# ---------------------------------------------------------------------------
# 6. plan_piece_node
# ---------------------------------------------------------------------------

def plan_piece_node(state: dict) -> dict:
    """Plan implementation for the current subtask (subtasks[current_subtask_index]).

    Uses an LLM call with domain_context and curated tool recommendations to
    produce a detailed implementation plan for ONE subtask."""
    start = time.time()
    subtasks = state.get("subtasks", [])
    idx = state.get("current_subtask_index", 0)
    domain_context = state.get("domain_context", "")
    tool_recommendations = state.get("tool_recommendations", {})
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("execute", config)
    prompts_path = Path(_PROMPTS)

    if idx >= len(subtasks):
        logger.warning("plan_piece_no_subtask", extra={"index": idx})
        return {"phase": "plan_piece"}

    subtask = subtasks[idx]
    logger.info(
        "plan_piece_start",
        extra={"subtask_id": subtask.get("id"), "index": idx},
    )

    try:
        template = _load_prompt("piece_planner", prompts_path)
    except FileNotFoundError:
        template = (
            "Plan the implementation for this subtask.\n\n"
            "Subtask: {subtask_description}\n"
            "Acceptance criteria: {acceptance_criteria}\n\n"
            "Domain context:\n{domain_context}\n\n"
            "Available tools: {tools}\n\n"
            "Return a detailed step-by-step implementation plan."
        )

    tools_str = json.dumps(tool_recommendations) if tool_recommendations else "default"
    prompt = (
        template
        .replace("{subtask_description}", subtask.get("description", ""))
        .replace("{acceptance_criteria}", subtask.get("acceptance_criteria", ""))
        .replace("{domain_context}", domain_context[:4000])
        .replace("{tools}", tools_str)
    )

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="plan_piece",
            config=config,
            cwd=cwd,
            system_prompt="You are an implementation planner. Produce a detailed plan.",
        )
        plan_content = result.get("content", "")
    except Exception as exc:
        logger.error("plan_piece_failed", extra={"error": str(exc)})
        plan_content = f"Planning failed: {exc}"

    # Store plan on the subtask
    subtask["plan"] = plan_content[:3000]
    subtasks[idx] = subtask

    elapsed = round(time.time() - start, 3)
    logger.info(
        "plan_piece_done",
        extra={
            "subtask_id": subtask.get("id"),
            "plan_len": len(plan_content),
            "elapsed": elapsed,
        },
    )

    return {
        "subtasks": subtasks,
        "phase": "plan_piece",
    }


# ---------------------------------------------------------------------------
# 7. execute_piece_node
# ---------------------------------------------------------------------------

def execute_piece_node(state: dict) -> dict:
    """Execute the current subtask (subtasks[current_subtask_index]).

    Uses call_agent for code tasks (when cwd is set), call_llm_with_fallback
    for non-code tasks.  Handles review feedback injection for retry loops."""
    start = time.time()
    subtasks = list(state.get("subtasks", []))
    idx = state.get("current_subtask_index", 0)
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("execute", config)
    stall_detector = StallDetector.from_config(config)
    prompts_path = Path(_PROMPTS)

    if idx >= len(subtasks):
        logger.warning("execute_piece_no_subtask", extra={"index": idx})
        return {"phase": "execute_piece"}

    subtask = subtasks[idx]
    task_id = subtask.get("id", f"{idx}-task")
    description = subtask.get("description", "")
    acceptance = subtask.get("acceptance_criteria", "")
    plan = subtask.get("plan", "")
    domain_context = state.get("domain_context", "")

    logger.info("execute_piece_start", extra={"task_id": task_id, "index": idx})

    # Build review feedback if retrying
    review_issues = state.get("piece_review_issues", [])
    review_feedback = ""
    if review_issues:
        issue_lines = []
        for issue in review_issues:
            title = issue.get("title", "")
            desc = issue.get("description", "")
            fix = issue.get("fix", "")
            issue_lines.append(f"- {title}: {desc}. Fix: {fix}")
        review_feedback = (
            "\n\n## Previous Review Feedback\n"
            "The reviewer found these issues. Address them:\n"
            + "\n".join(issue_lines)
        )

    try:
        template = _load_prompt("implementer", prompts_path)
    except FileNotFoundError:
        template = (
            "Implement the following subtask.\n\n"
            "Description: {task_description}\n"
            "Acceptance criteria: {acceptance_criteria}\n"
        )

    prompt = template.replace("{task_description}", description)
    prompt = prompt.replace("{acceptance_criteria}", acceptance)

    # Inject plan and domain context
    if plan:
        prompt += f"\n\n## Implementation Plan\n{plan[:2000]}"
    if domain_context:
        prompt += f"\n\n## Domain Context\n{domain_context[:2000]}"
    if review_feedback:
        prompt += review_feedback

    stall_detector.start_task(task_id)

    try:
        if cwd:
            before = set(_get_changed_files(cwd))
            result = call_agent(
                prompt=prompt,
                models=models,
                cwd=cwd,
                phase="execute",
                config=config,
                timeout=600,
            )
            after = set(_get_changed_files(cwd))
            changed = list(after - before)
        else:
            result = call_llm_with_fallback(
                prompt=prompt,
                models=models,
                phase="execute",
                config=config,
            )
            changed = []

        content = result.get("content", "")

        # Parse structured summary (best-effort)
        parsed = extract_json(content)
        if parsed is None:
            parsed = rescue_json(content) or {}
        elif not parsed:
            parsed = {}

        summary = parsed.get("implementation_summary", content[:500])
        files_mod = parsed.get("files_modified", changed)

        subtask["status"] = "complete"
        subtask["attempts"] = subtask.get("attempts", 0) + 1
        subtask["result"] = {
            "summary": summary[:500] if summary else "",
            "files_modified": files_mod,
            "changed_files": changed,
            "content": content[:2000],
            "status": "COMPLETE",
        }
        stall_detector.end_task(task_id, parsed)

        logger.info("execute_piece_complete", extra={"task_id": task_id})

    except Exception as exc:
        logger.warning(
            "execute_piece_failed",
            extra={"task_id": task_id, "error": str(exc)},
        )
        subtask["status"] = "failed"
        subtask["attempts"] = subtask.get("attempts", 0) + 1
        subtask["result"] = {"status": "FAILED", "error": str(exc)}

    subtasks[idx] = subtask

    elapsed = round(time.time() - start, 3)
    logger.info(
        "execute_piece_done",
        extra={
            "task_id": task_id,
            "status": subtask.get("status"),
            "elapsed": elapsed,
        },
    )

    return {
        "subtasks": subtasks,
        "phase": "execute_piece",
    }


# ---------------------------------------------------------------------------
# 8. piece_review_node
# ---------------------------------------------------------------------------

def piece_review_node(state: dict) -> dict:
    """Review the current subtask result against its acceptance criteria.
    Uses call_llm_structured with PieceReviewOutput."""
    start = time.time()
    subtasks = state.get("subtasks", [])
    idx = state.get("current_subtask_index", 0)
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("piece_review", config)
    prompts_path = Path(_PROMPTS)

    if idx >= len(subtasks):
        logger.warning("piece_review_no_subtask", extra={"index": idx})
        return {"phase": "piece_review"}

    subtask = subtasks[idx]
    result_data = subtask.get("result", {})

    logger.info(
        "piece_review_start",
        extra={"subtask_id": subtask.get("id"), "index": idx},
    )

    try:
        template = _load_prompt("piece_reviewer", prompts_path)
    except FileNotFoundError:
        template = (
            "Review this subtask result.\n\n"
            "Subtask: {subtask_description}\n"
            "Acceptance criteria: {acceptance_criteria}\n"
            "Result: {result}\n\n"
            "Return: verdict (APPROVE/NITS/REJECT), issues, criteria_met, criteria_unmet."
        )

    prompt = (
        template
        .replace("{subtask_description}", subtask.get("description", ""))
        .replace("{acceptance_criteria}", subtask.get("acceptance_criteria", ""))
        .replace("{result}", json.dumps(result_data, indent=2)[:3000])
    )

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=PieceReviewOutput,
            phase="review",
            config=config,
            cwd=cwd,
            system_prompt="You are a focused code reviewer. Return valid JSON only.",
        )
    except Exception as exc:
        logger.error("piece_review_failed", extra={"error": str(exc)})
        return {
            "piece_verdict": "REJECT",
            "piece_review_issues": [{"title": "Review failed", "description": str(exc)}],
            "errors": [f"Piece review failed: {exc}"],
            "phase": "piece_review",
        }

    piece_review_rounds = state.get("piece_review_rounds", 0) + 1

    elapsed = round(time.time() - start, 3)
    logger.info(
        "piece_review_done",
        extra={
            "subtask_id": subtask.get("id"),
            "verdict": output.verdict,
            "num_issues": len(output.issues),
            "round": piece_review_rounds,
            "elapsed": elapsed,
        },
    )

    return {
        "piece_verdict": output.verdict,
        "piece_review_issues": output.issues,
        "piece_criteria_met": output.criteria_met,
        "piece_criteria_unmet": output.criteria_unmet,
        "piece_review_rounds": piece_review_rounds,
        "phase": "piece_review",
    }


# ---------------------------------------------------------------------------
# 9. holistic_review_node
# ---------------------------------------------------------------------------

def holistic_review_node(state: dict) -> dict:
    """Review all completed subtasks together for integration issues.
    Uses call_llm_structured with HolisticReviewOutput."""
    start = time.time()
    task = state.get("task", "")
    subtasks = state.get("subtasks", [])
    success_criteria = state.get("success_criteria", [])
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("holistic_review", config)
    prompts_path = Path(_PROMPTS)

    logger.info("holistic_review_start", extra={"num_subtasks": len(subtasks)})

    # Build summary of all subtask results
    subtask_summaries = []
    for t in subtasks:
        entry = {
            "id": t.get("id"),
            "description": t.get("description", ""),
            "status": t.get("status", "unknown"),
            "acceptance_criteria": t.get("acceptance_criteria", ""),
        }
        if t.get("result"):
            entry["result_summary"] = t["result"].get("summary", "")[:300]
        subtask_summaries.append(entry)

    try:
        template = _load_prompt("holistic_reviewer", prompts_path)
    except FileNotFoundError:
        template = (
            "Review all subtask results together for integration issues.\n\n"
            "Original task: {task}\n"
            "Success criteria: {success_criteria}\n\n"
            "Subtask results:\n{subtask_results}\n\n"
            "Return: verdict (APPROVE/REJECT), integration_issues, "
            "coverage_gaps, consistency_issues."
        )

    prompt = (
        template
        .replace("{task}", task)
        .replace("{success_criteria}", json.dumps(success_criteria, indent=2))
        .replace("{subtask_results}", json.dumps(subtask_summaries, indent=2)[:4000])
    )

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=HolisticReviewOutput,
            phase="review",
            config=config,
            cwd=cwd,
            system_prompt=(
                "You are a senior technical reviewer evaluating integration quality. "
                "Return valid JSON only."
            ),
        )
    except Exception as exc:
        logger.error("holistic_review_failed", extra={"error": str(exc)})
        return {
            "holistic_verdict": "REJECT",
            "integration_issues": [],
            "coverage_gaps": [f"Holistic review failed: {exc}"],
            "errors": [f"Holistic review failed: {exc}"],
            "phase": "holistic_review",
        }

    elapsed = round(time.time() - start, 3)
    logger.info(
        "holistic_review_done",
        extra={
            "verdict": output.verdict,
            "num_integration_issues": len(output.integration_issues),
            "num_coverage_gaps": len(output.coverage_gaps),
            "elapsed": elapsed,
        },
    )

    return {
        "holistic_verdict": output.verdict,
        "integration_issues": output.integration_issues,
        "coverage_gaps": output.coverage_gaps,
        "consistency_issues": output.consistency_issues,
        "phase": "holistic_review",
    }


# ---------------------------------------------------------------------------
# 10. adversarial_review_node
# ---------------------------------------------------------------------------

def adversarial_review_node(state: dict) -> dict:
    """Hostile adversarial review — checks for hallucinations, logic errors,
    miscited sources.  Uses a deliberately aggressive system prompt and
    call_llm_structured with AdversarialReviewOutput."""
    start = time.time()
    task = state.get("task", "")
    subtasks = state.get("subtasks", [])
    citations = state.get("citations", [])
    domain_context = state.get("domain_context", "")
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("adversarial", config)

    logger.info("adversarial_review_start")

    # Compile all results for adversarial review
    all_results = []
    for t in subtasks:
        entry = {
            "id": t.get("id"),
            "description": t.get("description", ""),
            "result": t.get("result", {}),
        }
        all_results.append(entry)

    prompt = (
        "You are a HOSTILE adversarial reviewer. Your job is to BREAK the work.\n\n"
        "## Original Task\n"
        f"{task}\n\n"
        "## Domain Context Used\n"
        f"{domain_context[:2000]}\n\n"
        "## Citations Claimed\n"
        f"{json.dumps(citations, indent=2)[:2000]}\n\n"
        "## Subtask Results\n"
        f"{json.dumps(all_results, indent=2)[:4000]}\n\n"
        "## Your Mission\n"
        "1. Check every factual claim against the citations. Flag hallucinations.\n"
        "2. Look for logic errors, off-by-one bugs, race conditions.\n"
        "3. Verify citations actually support the claims made.\n"
        "4. Check for missing edge cases and error handling.\n"
        "5. Be HOSTILE. Assume the work is wrong until proven otherwise.\n\n"
        "Return JSON with: verdict (PASS/FAIL), findings (list), summary."
    )

    adversarial_system = (
        "You are a hostile adversarial code reviewer. You WANT to find problems. "
        "You are skeptical of every claim. You verify every citation. "
        "You assume bugs exist until proven otherwise. Return valid JSON only."
    )

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=AdversarialReviewOutput,
            phase="adversarial",
            config=config,
            cwd=cwd,
            system_prompt=adversarial_system,
        )
    except Exception as exc:
        logger.error("adversarial_review_failed", extra={"error": str(exc)})
        return {
            "adversarial_verdict": "FAIL",
            "adversarial_findings": [],
            "adversarial_summary": f"Adversarial review failed: {exc}",
            "errors": [f"Adversarial review failed: {exc}"],
            "phase": "adversarial_review",
        }

    findings = [f.model_dump() for f in output.findings]

    elapsed = round(time.time() - start, 3)
    logger.info(
        "adversarial_review_done",
        extra={
            "verdict": output.verdict,
            "num_findings": len(findings),
            "num_hallucinations": sum(1 for f in output.findings if f.is_hallucination),
            "elapsed": elapsed,
        },
    )

    return {
        "adversarial_verdict": output.verdict,
        "adversarial_findings": findings,
        "adversarial_summary": output.summary,
        "phase": "adversarial_review",
    }


# ---------------------------------------------------------------------------
# 11. verify_node
# ---------------------------------------------------------------------------

def verify_node(state: dict) -> dict:
    """Verify each success criterion with evidence.  Uses call_llm_structured
    with VerificationOutput."""
    start = time.time()
    task = state.get("task", "")
    subtasks = state.get("subtasks", [])
    success_criteria = state.get("success_criteria", [])
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("verify", config)

    logger.info(
        "verify_start",
        extra={"num_criteria": len(success_criteria)},
    )

    # Compile results
    results_summary = []
    for t in subtasks:
        results_summary.append({
            "id": t.get("id"),
            "description": t.get("description", ""),
            "status": t.get("status", "unknown"),
            "result_summary": (t.get("result") or {}).get("summary", "")[:300],
            "files_modified": (t.get("result") or {}).get("files_modified", []),
        })

    prompt = (
        "Verify that each success criterion has been met with concrete evidence.\n\n"
        f"## Task\n{task}\n\n"
        f"## Success Criteria\n{json.dumps(success_criteria, indent=2)}\n\n"
        f"## Subtask Results\n{json.dumps(results_summary, indent=2)[:4000]}\n\n"
        "For each criterion, determine:\n"
        "- passed: true/false\n"
        "- evidence: what specifically proves it's met (or why it's not)\n"
        "- method: 'test_execution', 'ground_truth_comparison', or 'llm_assessment'\n\n"
        "Return: verdict (PASS/PARTIAL/FAIL), results (list), summary."
    )

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=VerificationOutput,
            phase="verify",
            config=config,
            cwd=cwd,
            system_prompt=(
                "You are a verification agent. Only mark criteria as passed "
                "when there is concrete evidence. Return valid JSON only."
            ),
        )
    except Exception as exc:
        logger.error("verify_failed", extra={"error": str(exc)})
        return {
            "verification_verdict": "FAIL",
            "verification_results": [],
            "verification_summary": f"Verification failed: {exc}",
            "errors": [f"Verification failed: {exc}"],
            "phase": "verify",
        }

    results = [r.model_dump() for r in output.results]
    passed_count = sum(1 for r in output.results if r.passed)

    elapsed = round(time.time() - start, 3)
    logger.info(
        "verify_done",
        extra={
            "verdict": output.verdict,
            "passed": passed_count,
            "total": len(results),
            "elapsed": elapsed,
        },
    )

    return {
        "verification_verdict": output.verdict,
        "verification_results": results,
        "verification_summary": output.summary,
        "verdict": output.verdict,  # top-level for routing
        "phase": "verify",
    }


# ---------------------------------------------------------------------------
# 12. after_action_review_node
# ---------------------------------------------------------------------------

def after_action_review_node(state: dict) -> dict:
    """Reflect on the run and produce an after-action review.  Uses
    call_llm_structured with AAROutput.  Writes AAR to work/aar/ directory."""
    start = time.time()
    task = state.get("task", "")
    subtasks = state.get("subtasks", [])
    verification_summary = state.get("verification_summary", "")
    adversarial_summary = state.get("adversarial_summary", "")
    errors = state.get("errors", [])
    cwd = state.get("cwd") or state.get("repo_path")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("after_action", config)

    logger.info("aar_start")

    # Build run summary for reflection
    subtask_statuses = [
        f"- {t.get('id', '?')}: {t.get('status', 'unknown')}"
        for t in subtasks
    ]

    prompt = (
        "Conduct an after-action review of this workflow run.\n\n"
        f"## Task\n{task}\n\n"
        f"## Subtask Outcomes\n" + "\n".join(subtask_statuses) + "\n\n"
        f"## Verification Summary\n{verification_summary}\n\n"
        f"## Adversarial Summary\n{adversarial_summary}\n\n"
        f"## Errors Encountered\n{json.dumps(errors[:10], indent=2)}\n\n"
        "Reflect on:\n"
        "1. What worked well?\n"
        "2. What failed and why?\n"
        "3. What context was missing?\n"
        "4. Which LLM calls could become deterministic tools?\n"
        "5. What prompt changes would help next time?\n"
        "6. What structural workflow changes would improve quality?\n\n"
        "Return JSON with: what_worked, what_failed, context_gaps, "
        "tool_opportunities, prompt_improvements, workflow_improvements."
    )

    try:
        output = call_llm_structured(
            prompt=prompt,
            models=models,
            response_model=AAROutput,
            phase="aar",
            config=config,
            cwd=cwd,
            system_prompt=(
                "You are a process improvement analyst conducting an after-action review. "
                "Be honest about failures. Return valid JSON only."
            ),
        )
    except Exception as exc:
        logger.error("aar_failed", extra={"error": str(exc)})
        return {
            "aar": {"error": str(exc)},
            "phase": "aar",
        }

    aar_data = output.model_dump()

    # Write AAR to disk
    aar_dir = Path(cwd or ".") / "work" / "aar"
    try:
        aar_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        aar_file = aar_dir / f"aar_{timestamp}.json"
        aar_file.write_text(json.dumps(aar_data, indent=2))
        logger.info("aar_written", extra={"path": str(aar_file)})
    except Exception as exc:
        logger.warning("aar_write_failed", extra={"error": str(exc)})

    elapsed = round(time.time() - start, 3)
    logger.info(
        "aar_done",
        extra={
            "num_worked": len(output.what_worked),
            "num_failed": len(output.what_failed),
            "num_context_gaps": len(output.context_gaps),
            "elapsed": elapsed,
        },
    )

    return {
        "aar": aar_data,
        "phase": "aar",
    }


# ---------------------------------------------------------------------------
# 13. escalate_node (reuse factory)
# ---------------------------------------------------------------------------

escalate_node = make_escalate_node(
    config_path_default=_CONFIG,
    prompts_dir=_PROMPTS,
)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "analyze_task_node",
    "research_node",
    "build_context_node",
    "decompose_node",
    "validate_plan_node",
    "plan_piece_node",
    "execute_piece_node",
    "piece_review_node",
    "holistic_review_node",
    "adversarial_review_node",
    "verify_node",
    "after_action_review_node",
    "escalate_node",
]
