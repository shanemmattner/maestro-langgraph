"""PR Review workflow nodes — fetch, analyze, synthesize."""

import json
import logging
import subprocess
from pathlib import Path

from langgraph.types import Send

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json
from .state import PRReviewState

logger = logging.getLogger(__name__)

DEFAULT_MODELS = ["claude-sonnet-4-6"]
DEFAULT_REVIEWERS = ["security", "correctness", "tests", "architecture"]


def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text()


def fetch_pr_node(state: PRReviewState) -> dict:
    """Fetch PR metadata and diff using the gh CLI."""
    pr_url = state.get("pr_url", "")
    if not pr_url:
        raise ValueError("pr_url is required")

    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json",
             "number,title,body,author,baseRefName,headRefName,files"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        pr_data = json.loads(result.stdout)

        diff_result = subprocess.run(
            ["gh", "pr", "diff", pr_url],
            capture_output=True, text=True, check=True, timeout=30,
        )

        changed_files = [f["path"] for f in pr_data.get("files", [])]
        author = pr_data.get("author", {})
        author_login = author.get("login", "") if isinstance(author, dict) else str(author)

        return {
            "pr_number": pr_data.get("number", 0),
            "pr_title": pr_data.get("title", ""),
            "pr_body": pr_data.get("body", ""),
            "pr_author": author_login,
            "base_branch": pr_data.get("baseRefName", ""),
            "head_branch": pr_data.get("headRefName", ""),
            "pr_diff": diff_result.stdout,
            "changed_files": changed_files,
            "phase": "fetch",
        }
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Failed to fetch PR data: {exc}") from exc


def fan_out_reviewers(state: PRReviewState) -> list[Send]:
    reviewers = DEFAULT_REVIEWERS

    return [
        Send(
            "reviewer_node",
            {
                "pr_title": state.get("pr_title", ""),
                "pr_diff": state.get("pr_diff", ""),
                "changed_files": state.get("changed_files", []),
                "current_persona": persona,
            }
        )
        for persona in reviewers
    ]


def reviewer_node(state: PRReviewState) -> dict:
    """Run a single reviewer persona against the PR diff."""
    persona = state.get("current_persona", "general")
    pr_title = state.get("pr_title", "")
    pr_diff = state.get("pr_diff", "")
    changed_files = state.get("changed_files", [])

    template = _load_prompt("analyzer")
    prompt = template.replace("{reviewer_persona}", f"a {persona} reviewer")
    prompt = prompt.replace("{pr_title}", pr_title)
    prompt = prompt.replace("{pr_diff}", pr_diff)
    prompt = prompt.replace("{changed_files}", "\n".join(changed_files))

    try:
        result = call_llm_with_fallback(
            prompt=prompt, models=DEFAULT_MODELS, phase="review",
            system_prompt=f"You are a {persona} code reviewer. Return valid JSON only.",
        )
        parsed = extract_json(result.get("content", ""))
        findings = parsed if isinstance(parsed, list) else []
    except Exception as exc:
        logger.warning("Reviewer %s failed: %s", persona, exc)
        findings = []

    return {"reviewer_results": [{"persona": persona, "findings": findings}]}


def collect_reviews(state: PRReviewState) -> dict:
    reviewer_results = state.get("reviewer_results", [])
    all_findings = []
    for result in reviewer_results:
        findings = result.get("findings", [])
        all_findings.extend(findings)

    return {"findings": all_findings, "phase": "analyze"}


def synthesize_node(state: PRReviewState) -> dict:
    pr_title = state.get("pr_title", "")
    findings = state.get("findings", [])

    template = _load_prompt("synthesizer")
    prompt = template.replace("{pr_title}", pr_title)
    prompt = prompt.replace("{findings}", json.dumps(findings, indent=2))

    try:
        result = call_llm_with_fallback(
            prompt=prompt, models=DEFAULT_MODELS, phase="synthesize",
            system_prompt="You are a code review synthesiser. Return valid JSON only.",
        )
        parsed = extract_json(result.get("content", ""))

        if parsed is None:
            return {"verdict": "REQUEST_CHANGES", "review_summary": "Failed to parse", "issues": [], "phase": "synthesize"}

        return {
            "verdict": parsed.get("verdict", "REQUEST_CHANGES"),
            "review_summary": parsed.get("summary", parsed.get("review_summary", "")),
            "issues": parsed.get("issues", []),
            "phase": "synthesize",
        }

    except Exception as exc:
        return {"verdict": "REQUEST_CHANGES", "review_summary": f"Synthesis failed: {exc}", "issues": [], "phase": "synthesize"}


def escalated_review_node(state: PRReviewState) -> dict:
    pr_title = state.get("pr_title", "")
    pr_diff = state.get("pr_diff", "")
    changed_files = state.get("changed_files", [])
    prior_issues = state.get("issues", [])
    prior_verdict = state.get("verdict", "")
    prior_summary = state.get("review_summary", "")

    template = _load_prompt("escalation_reviewer")

    context_parts = [
        f"## Prior Review Verdict: {prior_verdict}",
        f"## Prior Review Summary: {prior_summary}",
    ]
    if prior_issues:
        context_parts.append("## Prior Issues Found:")
        for issue in prior_issues:
            context_parts.append(f"- [{issue.get('severity', '?')}] {issue.get('title', '')} in {issue.get('file', '')}")

    context = "\n".join(context_parts)

    prompt = template.replace("{pr_title}", pr_title)
    prompt = prompt.replace("{pr_diff}", pr_diff)
    prompt = prompt.replace("{changed_files}", "\n".join(changed_files))
    prompt = prompt.replace("{prior_review_context}", context)

    try:
        result = call_llm_with_fallback(
            prompt=prompt, models=DEFAULT_MODELS, phase="escalation",
            system_prompt="You are a senior code reviewer. Return valid JSON only.",
        )
        parsed = extract_json(result.get("content", ""))

        if parsed is None:
            return {"escalated": True, "escalation_verdict": prior_verdict, "escalation_summary": "Escalation parse failed", "phase": "escalated_review"}

        return {
            "escalated": True,
            "escalation_verdict": parsed.get("verdict", prior_verdict),
            "escalation_summary": parsed.get("summary", prior_summary),
            "issues": parsed.get("issues", prior_issues),
            "phase": "escalated_review",
        }

    except Exception as exc:
        return {"escalated": True, "escalation_verdict": prior_verdict, "escalation_summary": f"Escalation failed: {exc}", "phase": "escalated_review"}
