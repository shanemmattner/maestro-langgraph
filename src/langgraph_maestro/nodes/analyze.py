"""Analyze node for bug_hunter workflow."""
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_analyze_node(config: Dict[str, Any], prompts_dir: str):
    """Factory function to create an analyze node."""
    prompts_path = Path(prompts_dir)
    
    def analyze_node(state: Dict[str, Any]) -> Dict[str, Any]:
        bug_description = state.get("bug_description", "")
        reproduction_output = state.get("reproduction_output", "")
        error_logs = state.get("error_logs", "")
        repo_context = state.get("repo_context", {})
        attempt = state.get("analyze_attempt", 0)
        max_attempts = config.get("loops", {}).get("max_analyze_attempts", 2)
        
        # Load prompt template
        prompt_template = _load_prompt("analyzer", prompts_path)
        
        # Build prompt
        prompt = prompt_template.format(
            bug_description=bug_description,
            reproduction_output=reproduction_output,
            error_logs=error_logs,
            repo_context=str(repo_context),
            attempt=attempt + 1,
            max_attempts=max_attempts
        )
        
        # Call LLM
        models = config.get("phases", {}).get("analyze", ["MiniMax-M2.5-highspeed"])
        response = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="analyze",
            config=config,
            system_prompt="You are an expert bug analyst. Analyze the bug reproduction to identify the root cause and affected code."
        )

        # Extract result
        result = extract_json(response.get("content", "") if isinstance(response, dict) else response) or {}
        
        root_cause = result.get("root_cause", "")
        affected_files = result.get("affected_files", [])
        analysis_confidence = result.get("analysis_confidence", 0.0)
        
        new_state = {
            "root_cause": root_cause,
            "affected_files": affected_files,
            "analysis_confidence": analysis_confidence,
            "analyze_attempt": attempt + 1,
        }
        
        # Route based on confidence
        if analysis_confidence >= 0.8:
            new_state["next_phase"] = "patch"
        elif attempt + 1 >= max_attempts:
            new_state["next_phase"] = "patch"  # Proceed anyway
        else:
            new_state["next_phase"] = "analyze"
            
        return new_state
    
    return analyze_node
