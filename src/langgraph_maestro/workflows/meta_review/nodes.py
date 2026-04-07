"""Meta Review workflow nodes."""
import json
from typing import Dict, Any
from langgraph_maestro.workflows.meta_review.state import MetaReviewState
from langgraph_maestro.core.llm import call_llm


def load_run(state: MetaReviewState) -> Dict[str, Any]:
    """Load run data from langfuse trace or log file."""
    trace_id = state.get("trace_id")
    log_file = state.get("log_file")
    
    if trace_id:
        # Load from langfuse trace
        from langgraph_maestro.core.langfuse import get_trace_data
        run_data = get_trace_data(trace_id)
        return {"run_data": run_data}
    elif log_file:
        # Load from jsonl file
        with open(log_file, 'r') as f:
            lines = f.readlines()
            run_data = [json.loads(line) for line in lines]
        return {"run_data": run_data}
    else:
        raise ValueError("Either trace_id or log_file must be provided")


def analyze(state: MetaReviewState) -> Dict[str, Any]:
    """Analyze the run data and extract summary and metrics."""
    run_data = state.get("run_data")
    if not run_data:
        return {"summary": "No run data available", "metrics": {}}
    
    prompt = f"""Analyze the following run data and provide:
1. A summary of what happened (2-3 sentences)
2. Key metrics extracted from the run

Run data:
{json.dumps(run_data, indent=2)}

Respond in JSON format:
{{
  "summary": "...",
  "metrics": {{...}}
}}"""

    result = call_llm(
        prompt=prompt,
        model="MiniMax-M2.5-highspeed",
        system_prompt="You are a data analysis assistant. Extract key insights and metrics.",
        phase="analyze",
    )
    
    content = result.get("content", "{}")
    try:
        # Try to extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"summary": content, "metrics": {}}
    
    return {
        "summary": data.get("summary"),
        "metrics": data.get("metrics", {}),
    }


def critique(state: MetaReviewState) -> Dict[str, Any]:
    """Critique the run and identify issues."""
    run_data = state.get("run_data")
    summary = state.get("summary")
    
    prompt = f"""Analyze the following run data and summary, then critique it:
- Identify any issues, errors, or problems
- Note any inefficiencies or areas for improvement

Run data:
{json.dumps(run_data, indent=2)}

Summary:
{summary}

Respond in JSON format:
{{
  "critique": "...",
  "issues": ["issue1", "issue2", ...]
}}"""

    result = call_llm(
        prompt=prompt,
        model="MiniMax-M2.5-highspeed",
        system_prompt="You are a code review assistant. Identify issues and problems.",
        phase="critique",
    )
    
    content = result.get("content", "{}")
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"critique": content, "issues": []}
    
    return {
        "critique": data.get("critique"),
        "issues": data.get("issues", []),
    }


def recommend(state: MetaReviewState) -> Dict[str, Any]:
    """Generate recommendations based on analysis and critique."""
    summary = state.get("summary")
    critique = state.get("critique")
    issues = state.get("issues", [])
    
    prompt = f"""Based on the summary and critique, provide recommendations:

Summary:
{summary}

Critique:
{critique}

Issues identified:
{json.dumps(issues, indent=2)}

Respond in JSON format:
{{
  "recommendations": ["rec1", "rec2", ...],
  "priority": "high|medium|low"
}}"""

    result = call_llm(
        prompt=prompt,
        model="MiniMax-M2.5-highspeed",
        system_prompt="You are a technical advisor. Provide actionable recommendations.",
        phase="recommend",
    )
    
    content = result.get("content", "{}")
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"recommendations": [], "priority": "medium"}
    
    return {
        "recommendations": data.get("recommendations", []),
        "priority": data.get("priority", "medium"),
    }


def report(state: MetaReviewState) -> Dict[str, Any]:
    """Generate final markdown report."""
    summary = state.get("summary", "N/A")
    metrics = state.get("metrics", {})
    critique = state.get("critique", "N/A")
    issues = state.get("issues", [])
    recommendations = state.get("recommendations", [])
    priority = state.get("priority", "medium")
    
    report = f"""# Meta Review Report

## Summary
{summary}

## Metrics
{json.dumps(metrics, indent=2) if metrics else "No metrics available"}

## Critique
{critique}

## Issues Identified
{"- " + "\n- ".join(issues) if issues else "No issues identified"}

## Recommendations
{"- " + "\n- ".join(recommendations) if recommendations else "No recommendations"}

## Priority
{priority.upper()}

---
*Generated by meta_review workflow*
"""
    
    return {"report": report}
