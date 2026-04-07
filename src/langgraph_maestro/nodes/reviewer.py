"""Reviewer node — processes a single reviewer persona for parallel execution."""

import logging
from pathlib import Path

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    return path.read_text()


def make_reviewer_node(
    prompts_dir: str = str(Path(__file__).parent.parent / "workflows" / "pr_review" / "prompts"),
    config_path_default: str = str(Path(__file__).parent.parent / "workflows" / "pr_review" / "config.yaml"),
) -> callable:
    """Create a reviewer_node that processes a single reviewer persona.
    
    Args:
        prompts_dir: Path to the prompts directory
        config_path_default: Default path to the config file
    """
    prompts_path = Path(prompts_dir)
    
    def reviewer_node(state: dict) -> dict:
        """Process a single reviewer persona for parallel execution.
        
        This node handles ONE reviewer persona and returns findings for that persona.
        Called multiple times in parallel via Send() fan-out.
        
        Args:
            state: Must contain pr_title, pr_diff, changed_files, current_persona
            
        Returns:
            Dictionary with reviewer_result containing persona and findings
        """
        pr_title = state.get("pr_title", "")
        pr_diff = state.get("pr_diff", "")
        changed_files = state.get("changed_files", [])
        current_persona = state.get("current_persona", "security")
        
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)
        models = get_models_for_phase("analyze", config)
        
        logger.info("reviewer_node_start", extra={
            "pr_title": pr_title,
            "persona": current_persona
        })
        
        template = _load_prompt("analyzer", prompts_path)
        prompt = template.replace("{reviewer_persona}", current_persona)
        prompt = prompt.replace("{pr_title}", pr_title)
        prompt = prompt.replace("{pr_diff}", pr_diff)
        prompt = prompt.replace("{changed_files}", "\n".join(changed_files))
        
        system_prompt = f"You are a {current_persona} code reviewer. Return valid JSON only."
        
        findings = []
        
        try:
            result = call_llm_with_fallback(
                prompt=prompt,
                models=models,
                phase="analyze",
                config=config,
                system_prompt=system_prompt,
            )
            content = result.get("content", "")
            parsed = extract_json(content)
            
            if parsed and isinstance(parsed, list):
                findings = parsed
            elif parsed and isinstance(parsed, dict) and "findings" in parsed:
                findings = parsed["findings"]
                
        except Exception as exc:
            logger.warning("reviewer_node_failed", extra={
                "persona": current_persona,
                "error": str(exc)
            })
        
        logger.info("reviewer_node_done", extra={
            "persona": current_persona,
            "num_findings": len(findings)
        })
        
        return {
            "reviewer_results": [{
                "persona": current_persona,
                "findings": findings,
            }]
        }

    return reviewer_node
