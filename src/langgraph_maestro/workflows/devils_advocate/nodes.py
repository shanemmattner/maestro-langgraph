"""Devil's Advocate workflow nodes — research, critique, defend, judge, report."""

import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from langgraph_maestro.core.config import load_config, get_models_for_phase, workflow_config_path
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json
from langgraph_maestro.core.tracing import trace_node
from .state import DevilsAdvocateState

logger = logging.getLogger(__name__)

# Path to Firecrawl search script (relative to repo root)
_FIRECRAWL_SCRIPT = ".claude/skills/web-scraper/firecrawl_search.py"


def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text()


def _firecrawl_search(query: str, cwd: str | None = None) -> str:
    """Run a Firecrawl search and return the output text."""
    try:
        result = subprocess.run(
            ["python3", _FIRECRAWL_SCRIPT, query],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=120,
        )
        return result.stdout.strip() if result.returncode == 0 else f"[search failed: {result.stderr.strip()}]"
    except subprocess.TimeoutExpired:
        return "[search timed out]"
    except Exception as exc:
        return f"[search error: {exc}]"


def _read_context_file(context_path: str | None) -> str:
    """Read optional context document."""
    if not context_path:
        return "No additional context provided."
    path = Path(context_path)
    if path.exists():
        try:
            return path.read_text()[:10000]  # Cap at 10k chars
        except Exception:
            return f"Could not read context file: {context_path}"
    return f"Context file not found: {context_path}"


def _get_repo_root() -> str:
    """Get the repo root directory for Firecrawl script resolution."""
    # Walk up from this file to find the repo root (contains pyproject.toml)
    current = Path(__file__).parent
    for _ in range(10):
        if (current / "pyproject.toml").exists():
            return str(current)
        current = current.parent
    return str(Path(__file__).parent.parent.parent)


@trace_node("devils_advocate:research_counter_evidence")
def research_counter_evidence_node(state: DevilsAdvocateState) -> dict:
    """Use Firecrawl to find counter-evidence: failed attempts, arguments against, contradicting research."""
    proposal = state.get("proposal", "")
    proposal_type = state.get("proposal_type", "")

    logger.info("research_counter_evidence_start", extra={"proposal_type": proposal_type})

    repo_root = _get_repo_root()

    # Build search queries based on proposal type and content
    # Extract key terms from proposal for targeted searches
    short_proposal = proposal[:100]
    searches = [
        f"{proposal_type} strategy failed {short_proposal}",
        f"why {proposal_type} {short_proposal} is wrong site:news.ycombinator.com OR site:reddit.com",
        f"{proposal_type} mistakes pitfalls {short_proposal}",
        f"research against {proposal_type} {short_proposal}",
        f"{proposal_type} failed case study {short_proposal}",
    ]

    counter_evidence = []
    for query in searches:
        logger.info("firecrawl_search", extra={"query": query[:80]})
        result = _firecrawl_search(query, cwd=repo_root)

        if result and not result.startswith("[search"):
            counter_evidence.append({
                "source": query,
                "argument": result[:2000],  # Cap per result
                "severity": "MEDIUM",  # Will be re-assessed by critique node
            })

    logger.info("research_counter_evidence_done", extra={"num_results": len(counter_evidence)})

    return {
        "counter_evidence": counter_evidence,
        "phase": "research_counter_evidence",
    }


@trace_node("devils_advocate:find_alternatives")
def find_alternatives_node(state: DevilsAdvocateState) -> dict:
    """Use Firecrawl to find alternative strategies, retrospectives, and contrarian takes."""
    proposal = state.get("proposal", "")
    proposal_type = state.get("proposal_type", "")

    logger.info("find_alternatives_start", extra={"proposal_type": proposal_type})

    repo_root = _get_repo_root()

    short_proposal = proposal[:100]
    searches = [
        f"alternative to {proposal_type} {short_proposal}",
        f"what I would do differently {proposal_type} {short_proposal}",
        f"contrarian take {proposal_type} {short_proposal}",
        f"better approach than {short_proposal}",
        f"{proposal_type} retrospective lessons learned {short_proposal}",
    ]

    alternatives = []
    for query in searches:
        logger.info("firecrawl_search", extra={"query": query[:80]})
        result = _firecrawl_search(query, cwd=repo_root)

        if result and not result.startswith("[search"):
            alternatives.append({
                "approach": query,
                "evidence": result[:2000],
                "tradeoffs": "",  # Will be filled by critique node
            })

    logger.info("find_alternatives_done", extra={"num_results": len(alternatives)})

    return {
        "alternatives": alternatives,
        "phase": "find_alternatives",
    }


@trace_node("devils_advocate:build_critique")
def build_critique_node(state: DevilsAdvocateState) -> dict:
    """Claude Opus synthesizes research into structured adversarial argument."""
    proposal = state.get("proposal", "")
    proposal_type = state.get("proposal_type", "")
    context_path = state.get("context_path")
    counter_evidence = state.get("counter_evidence", [])
    alternatives = state.get("alternatives", [])

    config_path = state.get("config_path", workflow_config_path(__file__))
    config = load_config(config_path)
    models = get_models_for_phase("build_critique", config)

    logger.info("build_critique_start", extra={"proposal_type": proposal_type, "models": models})

    context = _read_context_file(context_path)

    template = _load_prompt("critic")
    prompt = template.replace("{proposal}", proposal)
    prompt = prompt.replace("{proposal_type}", proposal_type)
    prompt = prompt.replace("{context}", context)
    prompt = prompt.replace("{counter_evidence}", json.dumps(counter_evidence, indent=2))
    prompt = prompt.replace("{alternatives}", json.dumps(alternatives, indent=2))

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="build_critique",
            config=config,
            system_prompt="You are a ruthless adversarial critic. Be thorough, specific, and evidence-based.",
        )
        critique = result.get("content", "")
    except Exception as exc:
        logger.error("build_critique_failed", extra={"error": str(exc)})
        return {
            "critique": f"Critique generation failed: {exc}",
            "errors": state.get("errors", []) + [f"build_critique failed: {exc}"],
            "phase": "build_critique",
        }

    logger.info("build_critique_done", extra={"critique_length": len(critique)})

    return {
        "critique": critique,
        "phase": "build_critique",
    }


@trace_node("devils_advocate:defend_proposal")
def defend_proposal_node(state: DevilsAdvocateState) -> dict:
    """Claude Sonnet (different model) writes rebuttal defending the proposal."""
    proposal = state.get("proposal", "")
    proposal_type = state.get("proposal_type", "")
    context_path = state.get("context_path")
    critique = state.get("critique", "")

    config_path = state.get("config_path", workflow_config_path(__file__))
    config = load_config(config_path)
    models = get_models_for_phase("defend_proposal", config)

    logger.info("defend_proposal_start", extra={"proposal_type": proposal_type, "models": models})

    context = _read_context_file(context_path)

    template = _load_prompt("defender")
    prompt = template.replace("{proposal}", proposal)
    prompt = prompt.replace("{proposal_type}", proposal_type)
    prompt = prompt.replace("{context}", context)
    prompt = prompt.replace("{critique}", critique)

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="defend_proposal",
            config=config,
            system_prompt="You are a persuasive advocate. Make the strongest possible case while staying honest.",
        )
        defense = result.get("content", "")
    except Exception as exc:
        logger.error("defend_proposal_failed", extra={"error": str(exc)})
        return {
            "defense": f"Defense generation failed: {exc}",
            "errors": state.get("errors", []) + [f"defend_proposal failed: {exc}"],
            "phase": "defend_proposal",
        }

    logger.info("defend_proposal_done", extra={"defense_length": len(defense)})

    return {
        "defense": defense,
        "phase": "defend_proposal",
    }


@trace_node("devils_advocate:judge_verdict")
def judge_verdict_node(state: DevilsAdvocateState) -> dict:
    """Claude Opus as impartial judge. Returns PROCEED/REVISE/ABANDON with confidence."""
    proposal = state.get("proposal", "")
    proposal_type = state.get("proposal_type", "")
    critique = state.get("critique", "")
    defense = state.get("defense", "")

    config_path = state.get("config_path", workflow_config_path(__file__))
    config = load_config(config_path)
    models = get_models_for_phase("judge_verdict", config)

    logger.info("judge_verdict_start", extra={"proposal_type": proposal_type, "models": models})

    template = _load_prompt("judge")
    prompt = template.replace("{proposal}", proposal)
    prompt = prompt.replace("{proposal_type}", proposal_type)
    prompt = prompt.replace("{critique}", critique)
    prompt = prompt.replace("{defense}", defense)

    try:
        result = call_llm_with_fallback(
            prompt=prompt,
            models=models,
            phase="judge_verdict",
            config=config,
            system_prompt="You are an impartial judge. Return valid JSON only.",
        )
        content = result.get("content", "")
        parsed = extract_json(content)

        if parsed is None:
            logger.error("judge_verdict_parse_failed")
            return {
                "verdict": "REVISE",
                "confidence_score": 0.0,
                "errors": state.get("errors", []) + ["judge_verdict: failed to parse JSON"],
                "phase": "judge_verdict",
            }

        verdict = parsed.get("verdict", "REVISE")
        confidence_score = float(parsed.get("confidence_score", 0.5))

        # Store the full judge reasoning for the report
        judge_reasoning = parsed.get("reasoning", "")
        strongest_critique = parsed.get("strongest_critique_points", [])
        strongest_defense = parsed.get("strongest_defense_points", [])
        conditions = parsed.get("conditions", [])

    except Exception as exc:
        logger.error("judge_verdict_failed", extra={"error": str(exc)})
        return {
            "verdict": "REVISE",
            "confidence_score": 0.0,
            "errors": state.get("errors", []) + [f"judge_verdict failed: {exc}"],
            "phase": "judge_verdict",
        }

    logger.info("judge_verdict_done", extra={"verdict": verdict, "confidence": confidence_score})

    return {
        "verdict": verdict,
        "confidence_score": confidence_score,
        "phase": "judge_verdict",
    }


@trace_node("devils_advocate:write_report")
def write_report_node(state: DevilsAdvocateState) -> dict:
    """Save decision doc to docs/decisions/YYYY-MM-DD-<topic>.md."""
    proposal = state.get("proposal", "")
    proposal_type = state.get("proposal_type", "")
    counter_evidence = state.get("counter_evidence", [])
    alternatives = state.get("alternatives", [])
    critique = state.get("critique", "")
    defense = state.get("defense", "")
    verdict = state.get("verdict", "REVISE")
    confidence_score = state.get("confidence_score", 0.0)
    errors = state.get("errors", [])

    logger.info("write_report_start", extra={"verdict": verdict})

    # Generate filename from proposal
    date_str = datetime.now().strftime("%Y-%m-%d")
    # Sanitize proposal into a slug
    slug = proposal[:60].lower()
    slug = "".join(c if c.isalnum() or c in ("-", " ") else "" for c in slug)
    slug = slug.strip().replace(" ", "-")
    slug = "-".join(part for part in slug.split("-") if part)  # Remove double dashes

    filename = f"{date_str}-{slug}.md"

    # Write to docs/decisions/ relative to the repo root
    repo_root = Path(_get_repo_root())
    decisions_dir = repo_root / "docs" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    report_path = decisions_dir / filename

    # Format counter-evidence for report
    evidence_section = ""
    for i, ev in enumerate(counter_evidence, 1):
        evidence_section += f"\n### {i}. {ev.get('source', 'Unknown')}\n"
        evidence_section += f"{ev.get('argument', '')[:500]}\n"

    # Format alternatives for report
    alternatives_section = ""
    for i, alt in enumerate(alternatives, 1):
        alternatives_section += f"\n### {i}. {alt.get('approach', 'Unknown')}\n"
        alternatives_section += f"{alt.get('evidence', '')[:500]}\n"

    # Build the report
    report = f"""# Decision: {proposal}

**Type**: {proposal_type}
**Date**: {date_str}
**Verdict**: {verdict}
**Confidence**: {confidence_score:.0%}

---

## Proposal

{proposal}

---

## Counter-Evidence Research
{evidence_section if evidence_section else "No counter-evidence found."}

---

## Alternative Approaches
{alternatives_section if alternatives_section else "No alternatives found."}

---

## Adversarial Critique

{critique}

---

## Defense

{defense}

---

## Verdict: {verdict} ({confidence_score:.0%} confidence)

"""

    if errors:
        report += "\n---\n\n## Errors During Analysis\n"
        for err in errors:
            report += f"- {err}\n"

    report += f"\n---\n\n*Generated by devils_advocate workflow on {date_str}*\n"

    try:
        report_path.write_text(report)
        logger.info("write_report_done", extra={"report_path": str(report_path)})
    except Exception as exc:
        logger.error("write_report_failed", extra={"error": str(exc)})
        return {
            "report_path": "",
            "errors": errors + [f"write_report failed: {exc}"],
            "phase": "write_report",
        }

    return {
        "report_path": str(report_path),
        "phase": "write_report",
    }
