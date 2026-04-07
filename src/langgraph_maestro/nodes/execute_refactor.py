"""Execute refactor node — performs the actual code refactoring."""

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback

logger = logging.getLogger(__name__)

# Default max iterations for execute phase
DEFAULT_MAX_ITERATIONS = 3


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def _run_command(cwd: str, cmd: list[str]) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def make_execute_refactor_node(
    config_path_default: str,
    prompts_dir: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> Callable[[dict], dict]:
    """Create an execute refactor node with the given configuration.
    
    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory
        max_iterations: Maximum number of refactor attempts
    """
    prompts_path = Path(prompts_dir)

    def execute_refactor_node(state: dict) -> dict:
        """Execute the refactoring plan.
        
        Iteratively applies changes based on the plan.
        Tracks iteration count to prevent infinite loops.
        """
        start = time.time()
        goal = state.get("goal", "")
        plan = state.get("plan", "")
        target_files = state.get("target_files", [])
        cwd = state.get("cwd")
        
        # Get current iteration from state (default 0)
        iteration = state.get("iteration", 0)
        execute_rounds = state.get("execute_rounds", 0) + 1

        if not cwd:
            return {"error": "cwd is required for execute_refactor_node", "execute_rounds": execute_rounds, "next_action": "verify"}

        if not plan:
            return {"error": "plan is required for execute_refactor_node", "execute_rounds": execute_rounds, "next_action": "verify"}
        
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("execute", config)
        
        logger.info(
            "execute_refactor_start",
            extra={"goal": goal, "iteration": iteration, "num_files": len(target_files)}
        )
        
        # Read current file contents
        file_contents = []
        cwd_path = Path(cwd)
        for rel_path in target_files:
            full_path = cwd_path / rel_path
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8")
                file_contents.append(f"## {rel_path}\n{content}\n")
        
        files_text = "\n\n".join(file_contents)
        
        # Build prompt
        template = _load_prompt("executor", prompts_path)
        if template:
            prompt = template.replace("{goal}", goal)
            prompt = prompt.replace("{plan}", plan)
            prompt = prompt.replace("{files}", files_text)
        else:
            prompt = f"""Execute this refactoring plan:

Goal: {goal}

Plan:
{plan}

Current file contents:
{files_text}

Apply the refactoring changes. Provide:
1. List of files to modify with the new content
2. Any shell commands to run (e.g., git status, tests)
3. Summary of changes made"""

        # PE pass
        pe_config = config.get("prompt_engineering", {})
        if pe_config.get("enabled") and "execute" in pe_config.get("phases", []):
            from langgraph_maestro.core.pe import improve_prompt
            prompt = improve_prompt(prompt, config=config)
        
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="execute",
            config=config,
            cwd=cwd,
        )
        
        execution_result = result.get("content", "")
        
        # Check if we need to continue iterating
        # Simple heuristic: if execution result contains "retry" or "again"
        # or if it looks like there's more work to do
        continue_refactor = "retry" in execution_result.lower() or "again" in execution_result.lower()
        
        if continue_refactor and iteration < max_iterations:
            iteration += 1
            next_action = "execute"
        else:
            next_action = "verify"
        
        elapsed = round(time.time() - start, 3)
        logger.info(
            "execute_refactor_done",
            extra={
                "goal": goal,
                "iteration": iteration,
                "next_action": next_action,
                "elapsed": elapsed,
            },
        )
        
        return {
            "execution_result": execution_result,
            "iteration": iteration,
            "execute_rounds": execute_rounds,
            "next_action": next_action,
            "phase": "execute",
        }

    return execute_refactor_node
