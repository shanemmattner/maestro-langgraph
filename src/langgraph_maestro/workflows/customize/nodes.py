"""Customize workflow nodes."""
import os
import yaml
from pathlib import Path
from typing import Any

from .state import CustomizeState
from langgraph_maestro.core.llm import call_llm


def survey_node(state: CustomizeState) -> dict[str, Any]:
    """Load all workflows from workflows/ directory and read their configs."""
    workflows_dir = Path(__file__).parent.parent.parent / "workflows"
    available_workflows = []
    
    for workflow_path in workflows_dir.iterdir():
        if not workflow_path.is_dir():
            continue
        if workflow_path.name.startswith("_") or workflow_path.name == "customize":
            continue
            
        # Try to read config.yaml
        config_path = workflow_path / "config.yaml"
        description = ""
        
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    description = config.get("description", "")
            except Exception:
                pass
        
        # Try to read README.md
        readme_path = workflow_path / "README.md"
        if readme_path.exists():
            try:
                with open(readme_path) as f:
                    readme_content = f.read()
                    if description:
                        description += "\n\n" + readme_content
                    else:
                        description = readme_content
            except Exception:
                pass
        
        available_workflows.append({
            "name": workflow_path.name,
            "description": description.strip(),
        })
    
    return {
        "available_workflows": available_workflows,
    }


def match_node(state: CustomizeState) -> dict[str, Any]:
    """LLM picks best-fit workflow using call_llm() with model 'minimax'."""
    user_request = state.get("user_request", "")
    available_workflows = state.get("available_workflows", [])
    
    if not available_workflows:
        return {
            "matched_workflow": None,
            "match_reasoning": "No workflows available to match against.",
        }
    
    workflow_list = "\n".join([
        f"- {w['name']}: {w['description'][:200]}..." 
        for w in available_workflows
    ])
    
    prompt = f"""Given the user request below, select the best-fit workflow from the available options.

User Request: {user_request}

Available Workflows:
{workflow_list}

Return a JSON object with the following structure:
{{
  "matched_workflow": {{
    "name": "workflow_name",
    "description": "brief description"
  }},
  "confidence": 0.85,
  "reasoning": "Explain why this workflow is the best fit."
}}

Return ONLY valid JSON, no markdown fences."""
    
    result = call_llm(
        prompt=prompt,
        model="MiniMax-M2.5-highspeed",
    )

    import json
    content = result.get("content", "") if isinstance(result, dict) else str(result)
    try:
        parsed = json.loads(content)
        return {
            "matched_workflow": parsed.get("matched_workflow"),
            "match_reasoning": parsed.get("reasoning", ""),
        }
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON from response
        import re
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
                return {
                    "matched_workflow": parsed.get("matched_workflow"),
                    "match_reasoning": parsed.get("reasoning", ""),
                }
            except Exception:
                pass

        # Fallback: return first workflow
        return {
            "matched_workflow": available_workflows[0],
            "match_reasoning": "Could not parse LLM response, using first available workflow.",
        }


def spec_node(state: CustomizeState) -> dict[str, Any]:
    """Generate customization using call_llm() with model 'claude-sonnet-4-6'."""
    user_request = state.get("user_request", "")
    matched_workflow = state.get("matched_workflow", {})
    match_reasoning = state.get("match_reasoning", "")
    
    if not matched_workflow:
        return {
            "customization_spec": None,
        }
    
    workflow_name = matched_workflow.get("name", "")
    
    prompt = f"""Generate a customization specification for the workflow based on the user's request.

User Request: {user_request}

Matched Workflow: {workflow_name}
Match Reasoning: {match_reasoning}

Generate a JSON object with customization specifications:
{{
  "workflow_name": "{workflow_name}",
  "customizations": {{
    "phases_to_enable": ["phase1", "phase2"],
    "phases_to_disable": [],
    "config_patches": {{
      "key": "value"
    }},
    "new_nodes": [],
    "modified_prompts": {{}}
  }},
  "reasoning": "Explain the customizations made."
}}

Return ONLY valid JSON, no markdown fences."""
    
    result = call_llm(
        prompt=prompt,
        model="MiniMax-M2.5-highspeed",
    )

    import json
    content = result.get("content", "") if isinstance(result, dict) else str(result)
    try:
        parsed = json.loads(content)
        return {
            "customization_spec": parsed,
        }
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON
        import re
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
                return {
                    "customization_spec": parsed,
                }
            except Exception:
                pass

        # Fallback
        return {
            "customization_spec": {
                "workflow_name": workflow_name,
                "customizations": {},
                "reasoning": "Could not parse LLM response.",
            },
        }


def output_node(state: CustomizeState) -> dict[str, Any]:
    """Format final markdown report."""
    user_request = state.get("user_request", "")
    matched_workflow = state.get("matched_workflow", {})
    match_reasoning = state.get("match_reasoning", "")
    customization_spec = state.get("customization_spec", {})
    
    report = f"""# Workflow Customization Report

## User Request
{user_request}

## Matched Workflow
**{matched_workflow.get('name', 'N/A')}**

{match_reasoning}

## Customization Specification

"""
    
    if customization_spec:
        customizations = customization_spec.get("customizations", {})
        report += f"""### Phases to Enable
{', '.join(customizations.get('phases_to_enable', ['None']))}

### Phases to Disable
{', '.join(customizations.get('phases_to_disable', ['None']))}

### Config Patches
```yaml
{yaml.dump(customizations.get('config_patches', {}), default_flow_style=False)}
```

### Reasoning
{customization_spec.get('reasoning', 'No reasoning provided.')}
"""
    
    return {
        "final_report": report,
    }
