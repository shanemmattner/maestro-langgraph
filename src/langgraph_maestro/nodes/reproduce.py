"""Reproduce node for bug_hunter workflow."""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_reproduce_node(config: Dict[str, Any], prompts_dir: str):
    """Factory function to create a reproduce node."""
    prompts_path = Path(prompts_dir)
    
    def reproduce_node(state: Dict[str, Any]) -> Dict[str, Any]:
        bug_description = state.get("bug_description", "")
        repo_context = state.get("repo_context", {})
        attempt = state.get("reproduce_attempt", 0)
        max_attempts = config.get("loops", {}).get("max_reproduce_attempts", 2)
        
        # Load prompt template
        prompt_template = _load_prompt("reproducer", prompts_path)
        
        # Build prompt with context
        prompt = prompt_template.format(
            bug_description=bug_description,
            repo_context=str(repo_context),
            attempt=attempt + 1,
            max_attempts=max_attempts
        )
        
        # Call LLM
        models = config.get("phases", {}).get("reproduce", ["MiniMax-M2.5-highspeed"])
        response = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="reproduce",
            config=config,
            system_prompt="You are an expert bug reproducer. Analyze the bug description and create a minimal test case to reproduce it."
        )

        # Extract result
        result = extract_json(response.get("content", "") if isinstance(response, dict) else response) or {}
        
        reproduction_output = result.get("reproduction_output", "")
        reproduction_success = result.get("reproduction_success", False)
        error_logs = result.get("error_logs", "")
        
        # Update state
        new_state = {
            "reproduction_output": reproduction_output,
            "reproduction_success": reproduction_success,
            "error_logs": error_logs,
            "reproduce_attempt": attempt + 1,
        }
        
        # Route based on success
        if reproduction_success:
            new_state["next_phase"] = "analyze"
        elif attempt + 1 >= max_attempts:
            new_state["next_phase"] = "end"
        else:
            new_state["next_phase"] = "reproduce"
            
        return new_state
    
    return reproduce_node
