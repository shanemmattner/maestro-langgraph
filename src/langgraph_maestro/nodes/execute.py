"""Execute node — runs subtasks and records results.

Does the work, records what happened. Review node judges quality.
"""

import logging
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_agent, call_llm_with_fallback, _get_changed_files, extract_json, rescue_json
from langgraph_maestro.core.stall import StallDetector

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_execute_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create an execute node with the given configuration.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def execute_node(state: dict) -> dict:
        """Execute subtasks sequentially.

        Each subtask is sent to an LLM. If cwd is set, uses call_agent
        (tool-enabled subprocess). Otherwise uses call_llm (text-only).
        Results are stored on subtasks for the review node to judge.
        """
        start = time.time()
        subtasks = list(state.get("subtasks", []))
        cwd = state.get("cwd") or state.get("repo_path")
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("execute", config)
        stall_detector = StallDetector.from_config(config)

        # Review feedback injection (for review → execute retry loops)
        review_issues = state.get("review_issues", [])
        review_feedback = ""
        if review_issues:
            issue_lines = []
            for issue in review_issues:
                title = issue.get("title", "")
                desc = issue.get("description", "")
                fix = issue.get("fix", "")
                loc = issue.get("location", "")
                issue_lines.append(f"- [{loc}] {title}: {desc}. Fix: {fix}")
            review_feedback = (
                "\n\n## Previous Review Feedback\n"
                "The reviewer found these issues in the previous round. Address them:\n"
                + "\n".join(issue_lines)
            )

        completed = []
        failed = []
        execute_log = []
        template = _load_prompt("implementer", prompts_path)

        # PE config for execute phase
        pe_config = config.get("prompt_engineering", {})
        pe_enabled = pe_config.get("enabled") and "execute" in pe_config.get("phases", [])

        logger.info("execute_start", extra={"num_subtasks": len(subtasks)})

        for task_dict in subtasks:
            task_id = task_dict["id"]
            description = task_dict.get("description", "")
            acceptance = task_dict.get("acceptance_criteria", "")

            stall_detector.start_task(task_id)

            prompt = template.replace("{task_description}", description)
            prompt = prompt.replace("{acceptance_criteria}", acceptance)
            if review_feedback:
                prompt += review_feedback

            # PE pass: improve prompt before LLM call
            if pe_enabled:
                from langgraph_maestro.core.pe import improve_prompt
                prompt = improve_prompt(prompt, config=config)

            try:
                if cwd:
                    # Code task: use tool-enabled agent, track file changes
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
                    # Non-code task: text-only LLM call
                    result = call_llm_with_fallback(
                        prompt=prompt,
                        models=models,
                        phase="execute",
                        config=config,
                    )
                    changed = []

                content = result.get("content", "")

                # Parse summary from content (best-effort)
                parsed = extract_json(content)
                if parsed is None:
                    parsed = rescue_json(content) or {}
                elif not parsed:
                    parsed = {}

                summary = parsed.get("implementation_summary", content[:500])
                files_mod = parsed.get("files_modified", changed)

                task_dict["status"] = "complete"
                task_dict["attempts"] = 1
                task_dict["result"] = {
                    "summary": summary[:500] if summary else "",
                    "files_modified": files_mod,
                    "changed_files": changed,
                    "content": content[:2000],
                    "status": "COMPLETE",
                }
                stall_detector.end_task(task_id, parsed)
                completed.append(task_id)

                execute_log.append({
                    "task_id": task_id,
                    "status": "complete",
                    "summary": summary[:500] if summary else "",
                    "full_content": content[:2000],
                })

                logger.info("task_complete", extra={"task_id": task_id})

            except Exception as e:
                logger.warning(
                    "task_failed",
                    extra={"task_id": task_id, "error": str(e)},
                )
                task_dict["status"] = "failed"
                task_dict["attempts"] = 1
                task_dict["result"] = {"status": "FAILED", "error": str(e)}
                failed.append(task_id)
                execute_log.append({
                    "task_id": task_id,
                    "status": "failed",
                    "error": str(e),
                })

            # Check for stall
            stall = stall_detector.check_timeout(task_id)
            if stall:
                logger.warning("task_stalled", extra={"task_id": task_id})
                break

        # Record wave completion for stall detection
        stall_detector.record_wave_completion(len(completed))

        elapsed = round(time.time() - start, 3)
        logger.info(
            "execute_done",
            extra={
                "completed": len(completed),
                "failed": len(failed),
                "elapsed": elapsed,
                "stalls": len(stall_detector.get_stalls()),
            },
        )

        return {
            "subtasks": subtasks,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "execute_log": execute_log,
            "stalls": stall_detector.get_stalls(),
            "phase": "execute",
        }

    return execute_node
