"""Test generation node — generates test cases from acceptance criteria before execution."""

import logging
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_agent

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_test_gen_node(
    config_path_default: str,
    prompts_dir: str,
) -> Callable[[dict], dict]:
    """Create a test generation node.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
    """
    prompts_path = Path(prompts_dir)

    def test_gen_node(state: dict) -> dict:
        """Generate test cases from subtask acceptance criteria."""
        start = time.time()
        subtasks = state.get("subtasks", [])
        cwd = state.get("cwd") or state.get("repo_path")
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)

        # Check if test_gen phase is configured; if not, skip
        phases = config.get("phases", {})
        if "test_gen" not in phases:
            return {
                "generated_tests": [],
                "phase": "test_gen",
            }

        if not cwd:
            logger.warning("test_gen_skip_no_cwd")
            return {"generated_tests": [], "phase": "test_gen"}

        models = get_models_for_phase("test_gen", config)

        logger.info("test_gen_start", extra={"num_subtasks": len(subtasks)})

        # Build acceptance criteria summary for test generation
        criteria_parts = []
        for t in subtasks:
            criteria_parts.append(
                f"- Subtask {t.get('id', '?')}: {t.get('description', '')}\n"
                f"  Acceptance: {t.get('acceptance_criteria', 'none')}\n"
                f"  Files: {', '.join(t.get('files_to_modify', []))}"
            )
        criteria_text = "\n".join(criteria_parts)

        template = _load_prompt("test_gen", prompts_path)
        task = state.get("task", "")
        prompt = template.replace("{task}", task)
        prompt = prompt.replace("{acceptance_criteria}", criteria_text)

        try:
            result = call_agent(
                prompt=prompt,
                models=models,
                cwd=cwd,
                phase="test_gen",
                config=config,
                timeout=300,
            )

            # Detect generated test files
            import subprocess
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd, capture_output=True, text=True,
            )
            test_files = []
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines():
                    fname = line[3:].strip()
                    if "test" in fname.lower() and fname.endswith(".py"):
                        test_files.append(fname)

            elapsed = round(time.time() - start, 3)
            logger.info(
                "test_gen_done",
                extra={"num_tests": len(test_files), "elapsed": elapsed},
            )

            return {
                "generated_tests": test_files,
                "phase": "test_gen",
            }

        except Exception as e:
            logger.warning("test_gen_failed", extra={"error": str(e)})
            return {"generated_tests": [], "phase": "test_gen"}

    return test_gen_node
