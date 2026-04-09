"""Adaptive workflow nodes — markdown-driven, no Pydantic.

Each node takes state dict, returns partial state update dict.
Uses call_llm_with_fallback + extract_json for permissive parsing.
Uses call_agent for act phase when cwd is set (tool-enabled execution).
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from langgraph_maestro.core.llm import (
    call_agent,
    call_llm_with_fallback,
    extract_json,
)

logger = logging.getLogger(__name__)

DEFAULT_MODELS = ["claude-sonnet-4-6"]

_PROMPTS = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    return (_PROMPTS / f"{name}.txt").read_text()


# ---------------------------------------------------------------------------
# 1. think_node
# ---------------------------------------------------------------------------

def think_node(state: dict) -> dict:
    """Analyze the task — understand what needs to be done."""
    task = state.get("task", "")
    cwd = state.get("cwd", "")

    prompt = _load_prompt("think").format(
        task=task,
        cwd=cwd or "(not specified)",
    )

    result = call_llm_with_fallback(prompt, DEFAULT_MODELS, phase="think")
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

    result = call_llm_with_fallback(prompt, DEFAULT_MODELS, phase="plan")
    content = result.get("content", "")

    parsed = extract_json(content)
    if parsed and "pieces" in parsed:
        pieces = parsed["pieces"]
        for p in pieces:
            p.setdefault("status", "pending")
            p.setdefault("id", "unknown")
            p.setdefault("description", "")
            p.setdefault("acceptance_criteria", "")
    else:
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

    prompt = _load_prompt("adversarial").format(
        task=task,
        context=context,
        plan=plan,
    )

    result = call_llm_with_fallback(prompt, DEFAULT_MODELS, phase="adversarial")
    content = result.get("content", "")

    parsed = extract_json(content)
    if parsed:
        approved = bool(parsed.get("approved", False))
        feedback = parsed.get("feedback", content)
    else:
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

    if current_index >= len(pieces):
        logger.warning("act_no_piece", extra={"index": current_index, "total": len(pieces)})
        return {"errors": state.get("errors", []) + ["No piece to execute"], "phase": "act"}

    piece = pieces[current_index]
    piece_id = piece.get("id", f"piece-{current_index}")
    piece_description = piece.get("description", "")
    acceptance_criteria = piece.get("acceptance_criteria", "")

    if piece_retries > 0:
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

    if cwd:
        result = call_agent(prompt, DEFAULT_MODELS, cwd=cwd, phase="act")
    else:
        result = call_llm_with_fallback(prompt, DEFAULT_MODELS, phase="act")

    content = result.get("content", "")
    files_changed = result.get("files_changed", [])

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

    if current_index >= len(pieces):
        return {"errors": state.get("errors", []) + ["No piece to verify"], "phase": "verify"}

    piece = pieces[current_index]
    piece_id = piece.get("id", f"piece-{current_index}")
    piece_description = piece.get("description", "")
    acceptance_criteria = piece.get("acceptance_criteria", "")

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

    result = call_llm_with_fallback(prompt, DEFAULT_MODELS, phase="verify")
    content = result.get("content", "")

    parsed = extract_json(content)
    if parsed:
        verified = bool(parsed.get("verified", False))
        issues = parsed.get("issues", "")
    else:
        logger.warning("verify_json_parse_failed")
        verified = False
        issues = content

    latest_result["verified"] = verified
    latest_result["issues"] = issues

    update: Dict[str, Any] = {
        "piece_results": piece_results,
        "phase": "verify",
    }

    if verified:
        update["current_piece_index"] = current_index + 1
        update["piece_retries"] = 0
        pieces = list(pieces)
        pieces[current_index] = {**piece, "status": "complete"}
        update["pieces"] = pieces
    else:
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
