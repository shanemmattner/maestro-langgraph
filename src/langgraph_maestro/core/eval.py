"""Subtask evaluation — generic LLM judge + Langfuse score logging."""

import logging
from typing import Any

from langgraph_maestro.core.tracing import is_langfuse_available, record_feedback

logger = logging.getLogger(__name__)

_EVAL_SYSTEM_PROMPT = (
    "You are a code reviewer evaluating whether a subtask was completed successfully. "
    "Given the task description, acceptance criteria, list of changed files, file contents, "
    "and agent output, determine if the task was completed. "
    "Read the actual file contents to verify the implementation matches acceptance criteria. "
    'Respond with ONLY valid JSON in the format: {"pass": true/false, "reason": "one sentence explanation"}'
)


def run_llm_judge(
    question: str,
    answer: str,
    rubric: str,
    model: str = "minimax:MiniMax-M2.5-highspeed",
    config: dict | None = None,
) -> dict[str, Any]:
    """Generic LLM judge. Returns {score: float, passed: bool, reason: str}."""
    prompt = f"""## Question/Task
{question}

## Answer/Output
{answer}

## Rubric
{rubric}

Rate the answer on a scale of 0.0 to 1.0. Return JSON: {{"score": 0.0-1.0, "passed": true/false, "reason": "one sentence"}}"""

    try:
        from langgraph_maestro.core.llm import call_llm, extract_json

        result = call_llm(
            prompt=prompt,
            model=model,
            system_prompt="You are an evaluation judge. Return valid JSON only.",
            timeout=60,
            config=config,
        )
        content = result.get("content", "").strip()
        parsed = extract_json(content) if content else None

        if parsed and "score" in parsed:
            return {
                "score": float(parsed.get("score", 0.0)),
                "passed": bool(parsed.get("passed", False)),
                "reason": str(parsed.get("reason", "")),
            }
    except Exception as e:
        logger.warning("llm_judge_failed", extra={"error": str(e)})

    return {"score": 0.0, "passed": False, "reason": "judge unavailable"}


def log_eval_to_langfuse(trace_id: str, score: float, passed: bool, comment: str = "") -> bool:
    """Log an eval score to Langfuse via REST API."""
    if not is_langfuse_available():
        return False
    label = "pass" if passed else "fail"
    return record_feedback(trace_id, score, comment=f"[{label}] {comment}")


def _read_file_contents(cwd: str, changed_files: list[str], max_lines: int = 500) -> str:
    """Read contents of changed files, capped at max_lines per file."""
    from pathlib import Path

    if not cwd or not changed_files:
        return "(no file contents available)"

    parts = []
    for f in changed_files:
        fpath = Path(cwd) / f
        if not fpath.is_file():
            parts.append(f"### {f}\n(file not found)")
            continue
        try:
            lines = fpath.read_text(errors="replace").splitlines()
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines.append(f"... truncated at {max_lines} lines")
            parts.append(f"### {f}\n```\n{chr(10).join(lines)}\n```")
        except Exception as e:
            parts.append(f"### {f}\n(read error: {e})")
    return "\n\n".join(parts) if parts else "(no file contents available)"


def evaluate_subtask(
    description: str,
    acceptance_criteria: str,
    agent_content: str,
    changed_files: list[str],
    model: str = "minimax:MiniMax-M2.5-highspeed",
    config: dict | None = None,
    cwd: str | None = None,
) -> dict:
    """Evaluate whether a subtask was completed successfully.

    Returns {"pass": bool, "reason": str}
    Falls back to {"pass": len(changed_files) > 0, "reason": "eval unavailable"} on failure.
    """
    file_contents = _read_file_contents(cwd, changed_files) if cwd else "(no file contents)"

    prompt = f"""## Task Description
{description}

## Acceptance Criteria
{acceptance_criteria}

## Changed Files
{chr(10).join(changed_files) if changed_files else "(none)"}

## File Contents
{file_contents}

## Agent Output
{agent_content}

Did the agent complete this subtask successfully? Respond with JSON: {{"pass": true/false, "reason": "one sentence explanation"}}"""

    try:
        from langgraph_maestro.core.llm import call_llm, extract_json

        result = call_llm(
            prompt=prompt,
            model=model,
            system_prompt=_EVAL_SYSTEM_PROMPT,
            timeout=60,
            config=config,
        )

        content = result.get("content", "").strip()
        if not content:
            return _fallback(changed_files, cwd)

        parsed = extract_json(content)
        if parsed is None or "pass" not in parsed or "reason" not in parsed:
            return _fallback(changed_files, cwd)

        pass_value = parsed.get("pass")
        if isinstance(pass_value, str):
            pass_value = pass_value.lower() in ("true", "yes", "1")

        return {"pass": bool(pass_value), "reason": str(parsed.get("reason", ""))}

    except Exception as e:
        logger.warning("eval_failed", extra={"error": str(e)})
        return _fallback(changed_files, cwd)


def _fallback(changed_files: list[str], cwd: str | None = None) -> dict:
    """Fallback evaluation based on file changes.

    Args:
        changed_files: List of changed file paths
        cwd: Working directory to check actual file sizes

    Returns:
        {"pass": bool, "reason": str}
    """
    if not changed_files:
        return {
            "pass": False,
            "reason": "eval unavailable, no files changed",
        }

    # Check if any file has substantial content (>5 lines)
    if cwd:
        from pathlib import Path
        for f in changed_files:
            fpath = Path(cwd) / f
            if fpath.is_file():
                try:
                    lines = fpath.read_text(errors="replace").splitlines()
                    if len(lines) > 5:
                        return {
                            "pass": True,
                            "reason": "eval unavailable, fallback to file diff (substantial content)",
                        }
                except Exception:
                    pass

    # Fallback: any file change is considered a pass
    return {
        "pass": True,
        "reason": "eval unavailable, fallback to file diff",
    }
