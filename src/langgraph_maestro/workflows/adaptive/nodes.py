"""Adaptive workflow nodes — markdown-driven, no Pydantic.

Each node takes state dict, returns partial state update dict.
Uses call_llm_with_fallback + extract_json for permissive parsing.
Uses call_agent for act phase when cwd is set (tool-enabled execution).
"""

import logging
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
    extract_json,
)

logger = logging.getLogger(__name__)

_CONFIG = workflow_config_path(__file__)
_PROMPTS = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    return (_PROMPTS / f"{name}.txt").read_text()


def _safe_get_models(phase: str, config: dict) -> List[str]:
    """Get models for a phase, falling back to 'think' if phase missing."""
    try:
        return get_models_for_phase(phase, config)
    except ValueError:
        logger.warning(
            "phase_not_in_config",
            extra={"phase": phase, "fallback": "think"},
        )
        return get_models_for_phase("think", config)


# ---------------------------------------------------------------------------
# 1. think_node
# ---------------------------------------------------------------------------

def think_node(state: dict) -> dict:
    """Analyze the task — understand what needs to be done."""
    task = state.get("task", "")
    cwd = state.get("cwd", "")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("think", config)

    prompt = _load_prompt("think").format(
        task=task,
        cwd=cwd or "(not specified)",
    )

    result = call_llm_with_fallback(prompt, models, phase="think", config=config)
    content = result.get("content", "")

    logger.info("think_done", extra={"content_length": len(content)})
    return {"context": content, "phase": "think"}


# ---------------------------------------------------------------------------
# 2. plan_node
# ---------------------------------------------------------------------------

def plan_node(state: dict) -> dict:
    """Create a step-by-step plan, broken into verifiable pieces."""
    task = state.get("task", "")
    context = state.get("context", "")
    adversarial_feedback = state.get("adversarial_feedback", "")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("plan", config)

    # Build adversarial section if we have feedback from a previous round
    if adversarial_feedback:
        adversarial_section = (
            f"## Previous Reviewer Feedback\n"
            f"The plan was rejected. Address this feedback:\n\n{adversarial_feedback}"
        )
    else:
        adversarial_section = ""

    prompt = _load_prompt("plan").format(
        task=task,
        context=context,
        adversarial_section=adversarial_section,
    )

    result = call_llm_with_fallback(prompt, models, phase="plan", config=config)
    content = result.get("content", "")

    # Parse pieces from JSON response
    parsed = extract_json(content)
    if parsed and "pieces" in parsed:
        pieces = parsed["pieces"]
        # Normalize each piece
        for p in pieces:
            p.setdefault("status", "pending")
            p.setdefault("id", "unknown")
            p.setdefault("description", "")
            p.setdefault("acceptance_criteria", "")
    else:
        # Fallback: single piece with the raw text
        logger.warning("plan_json_parse_failed", extra={"raw_length": len(content)})
        pieces = [{
            "id": "1-full-task",
            "description": content[:500],
            "acceptance_criteria": "Task completed as described",
            "status": "pending",
        }]

    logger.info("plan_done", extra={"num_pieces": len(pieces)})
    return {
        "plan": content,
        "pieces": pieces,
        "current_piece_index": 0,
        "piece_results": [],
        "piece_retries": 0,
        "phase": "plan",
    }


# ---------------------------------------------------------------------------
# 3. adversarial_review_node
# ---------------------------------------------------------------------------

def adversarial_review_node(state: dict) -> dict:
    """Critically review the plan before any work begins."""
    task = state.get("task", "")
    context = state.get("context", "")
    plan = state.get("plan", "")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("adversarial", config)

    prompt = _load_prompt("adversarial").format(
        task=task,
        context=context,
        plan=plan,
    )

    result = call_llm_with_fallback(prompt, models, phase="adversarial", config=config)
    content = result.get("content", "")

    # Parse approval decision
    parsed = extract_json(content)
    if parsed:
        approved = bool(parsed.get("approved", False))
        feedback = parsed.get("feedback", content)
    else:
        # Can't parse — treat as not approved to be safe
        logger.warning("adversarial_json_parse_failed")
        approved = False
        feedback = content

    replan_rounds = state.get("replan_rounds", 0)
    if not approved:
        replan_rounds += 1

    logger.info("adversarial_done", extra={"approved": approved, "replan_rounds": replan_rounds})
    return {
        "plan_approved": approved,
        "adversarial_feedback": feedback,
        "replan_rounds": replan_rounds,
        "phase": "adversarial_review",
    }


# ---------------------------------------------------------------------------
# 4. act_node
# ---------------------------------------------------------------------------

def act_node(state: dict) -> dict:
    """Execute the current piece of work."""
    task = state.get("task", "")
    plan = state.get("plan", "")
    pieces = state.get("pieces", [])
    current_index = state.get("current_piece_index", 0)
    piece_results = list(state.get("piece_results", []))
    piece_retries = state.get("piece_retries", 0)
    cwd = state.get("cwd", "")
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("act", config)

    if current_index >= len(pieces):
        logger.warning("act_no_piece", extra={"index": current_index, "total": len(pieces)})
        return {"errors": state.get("errors", []) + ["No piece to execute"], "phase": "act"}

    piece = pieces[current_index]
    piece_id = piece.get("id", f"piece-{current_index}")
    piece_description = piece.get("description", "")
    acceptance_criteria = piece.get("acceptance_criteria", "")

    # Build retry section if this is a retry
    if piece_retries > 0:
        # Find previous result for this piece
        prev_results = [r for r in piece_results if r.get("piece_id") == piece_id]
        if prev_results:
            last = prev_results[-1]
            retry_section = (
                f"## Previous Attempt (retry {piece_retries})\n"
                f"The previous attempt was not verified. Issues:\n"
                f"{last.get('issues', 'Unknown issues')}\n\n"
                f"Previous result:\n{last.get('result', '')[:500]}"
            )
        else:
            retry_section = f"## Retry {piece_retries}\nPrevious attempt failed verification."
    else:
        retry_section = ""

    prompt = _load_prompt("act").format(
        task=task,
        plan=plan,
        piece_id=piece_id,
        piece_description=piece_description,
        acceptance_criteria=acceptance_criteria,
        retry_section=retry_section,
    )

    # Use call_agent (tool-enabled) when we have a working directory
    if cwd:
        result = call_agent(prompt, models, cwd=cwd, phase="act", config=config)
    else:
        result = call_llm_with_fallback(prompt, models, phase="act", config=config)

    content = result.get("content", "")
    files_changed = result.get("files_changed", [])

    # Record the result
    piece_result = {
        "piece_id": piece_id,
        "result": content,
        "files_changed": files_changed,
        "verified": False,
    }
    piece_results.append(piece_result)

    logger.info("act_done", extra={"piece_id": piece_id, "files_changed": len(files_changed)})
    return {
        "piece_results": piece_results,
        "phase": "act",
    }


# ---------------------------------------------------------------------------
# 5. verify_node
# ---------------------------------------------------------------------------

def verify_node(state: dict) -> dict:
    """Verify the current piece was completed correctly."""
    pieces = state.get("pieces", [])
    current_index = state.get("current_piece_index", 0)
    piece_results = list(state.get("piece_results", []))
    piece_retries = state.get("piece_retries", 0)
    config_path = state.get("config_path", _CONFIG)
    config = load_config(config_path)
    models = _safe_get_models("verify", config)

    if current_index >= len(pieces):
        return {"errors": state.get("errors", []) + ["No piece to verify"], "phase": "verify"}

    piece = pieces[current_index]
    piece_id = piece.get("id", f"piece-{current_index}")
    piece_description = piece.get("description", "")
    acceptance_criteria = piece.get("acceptance_criteria", "")

    # Find the latest result for this piece
    matching_results = [r for r in piece_results if r.get("piece_id") == piece_id]
    if not matching_results:
        return {"errors": state.get("errors", []) + [f"No result for piece {piece_id}"], "phase": "verify"}

    latest_result = matching_results[-1]

    prompt = _load_prompt("verify").format(
        piece_id=piece_id,
        piece_description=piece_description,
        acceptance_criteria=acceptance_criteria,
        piece_result=latest_result.get("result", ""),
    )

    result = call_llm_with_fallback(prompt, models, phase="verify", config=config)
    content = result.get("content", "")

    parsed = extract_json(content)
    if parsed:
        verified = bool(parsed.get("verified", False))
        issues = parsed.get("issues", "")
    else:
        # Can't parse — assume not verified
        logger.warning("verify_json_parse_failed")
        verified = False
        issues = content

    # Update the latest result with verification status
    latest_result["verified"] = verified
    latest_result["issues"] = issues

    update: Dict[str, Any] = {
        "piece_results": piece_results,
        "phase": "verify",
    }

    if verified:
        # Advance to next piece, reset retries
        update["current_piece_index"] = current_index + 1
        update["piece_retries"] = 0
        # Mark piece as complete
        pieces = list(pieces)
        pieces[current_index] = {**piece, "status": "complete"}
        update["pieces"] = pieces
    else:
        # Increment retries
        update["piece_retries"] = piece_retries + 1

    logger.info("verify_done", extra={"piece_id": piece_id, "verified": verified, "retries": update.get("piece_retries", 0)})
    return update


# ---------------------------------------------------------------------------
# 6. done_node
# ---------------------------------------------------------------------------

def done_node(state: dict) -> dict:
    """Summarize the workflow results."""
    pieces = state.get("pieces", [])
    piece_results = state.get("piece_results", [])
    errors = state.get("errors", [])

    completed = sum(1 for p in pieces if p.get("status") == "complete")
    total = len(pieces)
    verified = sum(1 for r in piece_results if r.get("verified"))

    lines = [
        f"## Adaptive Workflow Complete",
        f"",
        f"**Pieces**: {completed}/{total} completed",
        f"**Verified**: {verified} results verified",
    ]

    if errors:
        lines.append(f"**Errors**: {len(errors)}")
        for e in errors:
            lines.append(f"  - {e}")

    if not state.get("plan_approved"):
        lines.append(f"**Note**: Plan was not approved after {state.get('replan_rounds', 0)} replan round(s).")

    # List files changed across all pieces
    all_files = []
    for r in piece_results:
        all_files.extend(r.get("files_changed", []))
    if all_files:
        lines.append(f"\n**Files changed**: {len(set(all_files))}")
        for f in sorted(set(all_files)):
            lines.append(f"  - {f}")

    summary = "\n".join(lines)
    logger.info("done", extra={"completed": completed, "total": total})
    return {"summary": summary, "phase": "done"}
