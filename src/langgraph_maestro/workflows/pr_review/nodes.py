"""PR Review workflow nodes — fetch, analyze, synthesize."""

import json
import logging
import re
import subprocess
from pathlib import Path

from langgraph.types import Send

from langgraph_maestro.core.config import load_config, get_models_for_phase, workflow_config_path
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json
from langgraph_maestro.nodes.fetch_pr import make_fetch_pr_node
from langgraph_maestro.nodes.reviewer import make_reviewer_node
from .state import PRReviewState

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text()


def _run(cmd: list[str], cwd: str | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        check=True,
        capture_output=capture,
    )


# Factory function for fetch_pr_node
fetch_pr_node = make_fetch_pr_node()


def fan_out_reviewers(state: PRReviewState) -> list[Send]:
    """Fan out to reviewer_node for each reviewer persona.
    
    Uses LangGraph's Send() API for parallel fan-out/fan-in pattern.
    
    Returns:
        List of Send() calls, one for each reviewer persona.
    """
    pr_title = state.get("pr_title", "")
    config_path = state.get("config_path", workflow_config_path(__file__))
    
    try:
        config = load_config(config_path)
        reviewers = config.get("reviewers", ["security", "correctness", "tests", "architecture"])
    except Exception:
        reviewers = ["security", "correctness", "tests", "architecture"]
    
    logger.info("fan_out_reviewers", extra={"pr_title": pr_title, "num_reviewers": len(reviewers)})
    
    # Create Send() for each persona, passing necessary state
    return [
        Send(
            "reviewer_node",
            {
                "pr_title": state.get("pr_title", ""),
                "pr_diff": state.get("pr_diff", ""),
                "changed_files": state.get("changed_files", []),
                "current_persona": persona,
                "config_path": config_path,
            }
        )
        for persona in reviewers
    ]


# Factory function for reviewer_node
reviewer_node = make_reviewer_node()


def collect_reviews(state: PRReviewState) -> dict:
    """Aggregate results from all parallel reviewer nodes.
    
    Collects all individual reviewer results and flattens findings for synthesis.
    
    Returns:
        Dictionary with aggregated findings and reviewer_results
    """
    reviewer_results = state.get("reviewer_results", [])
    
    # Flatten all findings from all reviewers
    all_findings = []
    for result in reviewer_results:
        findings = result.get("findings", [])
        all_findings.extend(findings)
    
    logger.info("collect_reviews_done", extra={
        "num_reviewers": len(reviewer_results),
        "total_findings": len(all_findings)
    })
    
    return {
        "findings": all_findings,
        "phase": "analyze",
    }


def analyze_node(state: PRReviewState) -> dict:
    """Analyze the PR with multiple reviewer personas."""
    pr_title = state.get("pr_title", "")
    pr_diff = state.get("pr_diff", "")
    changed_files = state.get("changed_files", [])

    config_path = state.get("config_path", workflow_config_path(__file__))
    config = load_config(config_path)
    models = get_models_for_phase("analyze", config)

    reviewers = config.get("reviewers", ["security", "correctness", "tests", "architecture"])

    logger.info("analyze_start", extra={"pr_title": pr_title, "reviewers": reviewers})

    template = _load_prompt("analyzer")

    all_findings = []

    for persona in reviewers:
        prompt = template.replace("{reviewer_persona}", persona)
        prompt = prompt.replace("{pr_title}", pr_title)
        prompt = prompt.replace("{pr_diff}", pr_diff)
        prompt = prompt.replace("{changed_files}", "\n".join(changed_files))

        system_prompt = f"You are a {persona} code reviewer. Return valid JSON only."

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
                all_findings.extend(parsed)
            elif parsed and isinstance(parsed, dict) and "findings" in parsed:
                all_findings.extend(parsed["findings"])

        except Exception as exc:
            logger.warning("analyze_persona_failed", extra={"persona": persona, "error": str(exc)})
            continue

    logger.info("analyze_done", extra={"num_findings": len(all_findings)})

    return {
        "findings": all_findings,
        "phase": "analyze",
    }


def synthesize_node(state: PRReviewState) -> dict:
    """Synthesize findings into a final review verdict."""
    pr_title = state.get("pr_title", "")
    findings = state.get("findings", [])

    config_path = state.get("config_path", workflow_config_path(__file__))
    config = load_config(config_path)
    models = get_models_for_phase("synthesize", config)

    logger.info("synthesize_start", extra={"pr_title": pr_title})

    template = _load_prompt("synthesizer")
    prompt = template.replace("{pr_title}", pr_title)
    prompt = prompt.replace("{findings}", json.dumps(findings, indent=2))

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="synthesize",
            config=config,
            system_prompt="You are a code review synthesiser. Return valid JSON only.",
        )
        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.error("synthesize_parse_failed")
            return {
                "verdict": "REQUEST_CHANGES",
                "review_summary": "Failed to parse synthesis output",
                "issues": [{"severity": "HIGH", "title": "Synthesis parse failed"}],
                "phase": "synthesize",
            }

        verdict = parsed.get("verdict", "REQUEST_CHANGES")
        review_summary = parsed.get("summary", parsed.get("review_summary", ""))
        issues = parsed.get("issues", [])

    except Exception as exc:
        logger.error("synthesize_failed", extra={"error": str(exc)})
        return {
            "verdict": "REQUEST_CHANGES",
            "review_summary": f"Synthesis failed: {exc}",
            "issues": [{"severity": "HIGH", "title": "Synthesis failed"}],
            "phase": "synthesize",
        }

    logger.info("synthesize_done", extra={"verdict": verdict, "num_issues": len(issues)})

    return {
        "verdict": verdict,
        "review_summary": review_summary,
        "issues": issues,
        "phase": "synthesize",
    }


def _normalize_issues(issues: list[dict]) -> list[dict]:
    """Normalize issue dict keys to handle varying model outputs.
    
    Handles alternative key names:
    - 'title': fallback to 'name' or 'summary'
    - 'file': fallback to 'location', 'path', or 'filename'
    - 'severity': default to 'medium'
    - 'description': default to ''
    """
    if not issues:
        return []
    
    valid_severities = {"HIGH", "MEDIUM", "LOW"}
    normalized = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        sev = issue.get("severity", "medium").upper()
        if sev not in valid_severities:
            sev = "MEDIUM"
        normalized.append({
            'title': issue.get('title', issue.get('name', issue.get('summary', 'Untitled'))),
            'file': issue.get('file', issue.get('location', issue.get('path', issue.get('filename', '')))),
            'severity': sev,
            'description': issue.get('description', ''),
        })
    return normalized


def escalated_review_node(state: PRReviewState) -> dict:
    """Re-review PR with stronger model after initial REJECT verdict.
    
    This node is triggered when the initial review verdict is REQUEST_CHANGES or REJECT.
    It uses a stronger model to do a more thorough review, passing prior issues as context.
    """
    pr_title = state.get("pr_title", "")
    pr_diff = state.get("pr_diff", "")
    changed_files = state.get("changed_files", [])
    prior_issues = state.get("issues", [])
    prior_findings = state.get("findings", [])
    prior_verdict = state.get("verdict", "")
    prior_summary = state.get("review_summary", "")

    config_path = state.get("config_path", workflow_config_path(__file__))
    config = load_config(config_path)
    
    # Use escalation models (stronger) instead of analyze models
    models = get_models_for_phase("escalation", config)

    escalation_config = config.get("escalation", {})
    include_prior_issues = escalation_config.get("include_prior_issues", True)

    logger.info("escalated_review_start", extra={
        "pr_title": pr_title,
        "prior_verdict": prior_verdict,
        "prior_issues_count": len(prior_issues)
    })

    template = _load_prompt("escalation_reviewer")
    
    # Build context from prior review
    context_parts = [
        f"## Prior Review Verdict: {prior_verdict}",
        f"## Prior Review Summary: {prior_summary}",
    ]
    
    if include_prior_issues and prior_issues:
        context_parts.append("## Prior Issues Found:")
        for issue in prior_issues:
            severity = issue.get("severity", "UNKNOWN")
            title = issue.get("title", "Untitled")
            description = issue.get("description", "")
            file = issue.get("file", "unknown")
            context_parts.append(f"- [{severity}] {title} in {file}: {description}")
    
    if include_prior_issues and prior_findings:
        context_parts.append("## Prior Findings:")
        for finding in prior_findings:
            context_parts.append(f"- {finding}")

    context = "\n".join(context_parts)

    prompt = template.replace("{pr_title}", pr_title)
    prompt = prompt.replace("{pr_diff}", pr_diff)
    prompt = prompt.replace("{changed_files}", "\n".join(changed_files))
    prompt = prompt.replace("{prior_review_context}", context)

    system_prompt = """You are a senior code reviewer conducting a second-pass escalation review.
The initial review flagged issues. Please do a thorough re-review considering:
1. Are the prior issues valid?
2. Are there additional issues the first pass missed?
3. Is the prior verdict appropriate?

Return valid JSON only."""

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="escalation",
            config=config,
            system_prompt=system_prompt,
        )
        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.error("escalation_parse_failed")
            return {
                "escalated": True,
                "escalation_verdict": prior_verdict,  # Keep prior on failure
                "escalation_summary": "Escalation parse failed, retaining prior verdict",
                "phase": "escalated_review",
            }

        escalation_verdict = parsed.get("verdict", prior_verdict)
        escalation_summary = parsed.get("summary", parsed.get("review_summary", prior_summary))
        escalation_issues = parsed.get("issues", prior_issues)  # Merge or replace
        escalation_issues = _normalize_issues(escalation_issues)

    except Exception as exc:
        logger.error("escalation_failed", extra={"error": str(exc)})
        return {
            "escalated": True,
            "escalation_verdict": prior_verdict,
            "escalation_summary": f"Escalation failed: {exc}",
            "phase": "escalated_review",
        }

    logger.info("escalated_review_done", extra={
        "escalation_verdict": escalation_verdict,
        "prior_verdict": prior_verdict,
        "verdict_changed": escalation_verdict != prior_verdict
    })

    return {
        "escalated": True,
        "escalation_verdict": escalation_verdict,
        "escalation_summary": escalation_summary,
        "issues": escalation_issues,
        "phase": "escalated_review",
    }
