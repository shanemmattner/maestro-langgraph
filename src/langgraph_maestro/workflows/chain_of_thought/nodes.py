"""Chain-of-thought workflow nodes: decompose → reason steps → synthesize."""
import logging
from pathlib import Path
from typing import Any, Dict, List

from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text()


def _get_models(phase: str, config: Dict[str, Any]) -> list:
    return config.get("phases", {}).get(phase, ["MiniMax-M2.5-highspeed"])


def _call(phase: str, prompt: str, system_prompt: str, config: Dict[str, Any]) -> dict:
    models = _get_models(phase, config)
    response = call_llm_with_fallback(
        prompt=prompt,
        models=models,
        phase=phase,
        config=config,
        system_prompt=system_prompt,
    )
    content = response.get("content", "") if isinstance(response, dict) else response
    return extract_json(content) or {}


def make_decompose_node(config: Dict[str, Any]):
    """Break question into sub-questions and identify assumptions."""
    def decompose_node(state: Dict[str, Any]) -> Dict[str, Any]:
        question = state.get("question", "")
        context = state.get("context", "none")
        domain = state.get("domain", "general")

        prompt = (_load_prompt("decomposer")
                  .replace("{question}", question)
                  .replace("{domain}", domain)
                  .replace("{context}", context))

        result = _call("decompose", prompt, "You are an expert analytical thinker.", config)
        sub_questions = result.get("sub_questions", [question])
        if not sub_questions:
            sub_questions = [question]

        return {
            "sub_questions": sub_questions,
            "assumptions": result.get("assumptions", []),
        }
    return decompose_node


def make_reason_node(config: Dict[str, Any]):
    """Reason through all sub-questions sequentially."""
    def reason_node(state: Dict[str, Any]) -> Dict[str, Any]:
        question = state.get("question", "")
        context = state.get("context", "none")
        sub_questions = state.get("sub_questions", [])
        reasoning_steps = []

        for i, sub_q in enumerate(sub_questions):
            # Build previous steps summary
            prev_steps = ""
            if reasoning_steps:
                parts = []
                for step in reasoning_steps:
                    parts.append(f"Step {step['step_num']}: {step['sub_question']}\n→ {step['conclusion']}")
                prev_steps = "\n\n".join(parts)
            else:
                prev_steps = "(none yet)"

            prompt = (_load_prompt("reasoner")
                      .replace("{question}", question)
                      .replace("{step_num}", str(i + 1))
                      .replace("{sub_question}", sub_q)
                      .replace("{context}", context)
                      .replace("{previous_steps}", prev_steps))

            result = _call("reason", prompt, "You are a careful analytical reasoner.", config)
            reasoning_steps.append({
                "step_num": i + 1,
                "sub_question": sub_q,
                "reasoning": result.get("reasoning", ""),
                "conclusion": result.get("conclusion", ""),
                "confidence": float(result.get("confidence", 0.7)),
                "caveats": result.get("caveats", []),
            })
            logger.info("Completed reasoning step %d/%d", i + 1, len(sub_questions))

        return {"reasoning_steps": reasoning_steps}
    return reason_node


def make_synthesize_node(config: Dict[str, Any]):
    """Synthesize all reasoning steps into a final answer."""
    def synthesize_node(state: Dict[str, Any]) -> Dict[str, Any]:
        question = state.get("question", "")
        assumptions = state.get("assumptions", [])
        reasoning_steps = state.get("reasoning_steps", [])

        steps_text = ""
        for step in reasoning_steps:
            steps_text += (
                f"\n## Step {step['step_num']}: {step['sub_question']}\n"
                f"Reasoning: {step['reasoning']}\n"
                f"Conclusion: {step['conclusion']}\n"
            )

        prompt = (_load_prompt("synthesizer")
                  .replace("{question}", question)
                  .replace("{reasoning_steps}", steps_text)
                  .replace("{assumptions}", "\n".join(f"- {a}" for a in assumptions)))

        result = _call("synthesize", prompt, "You are an analytical synthesizer.", config)

        return {
            "answer": result.get("answer", ""),
            "confidence": float(result.get("confidence", 0.7)),
            "key_assumptions": result.get("key_assumptions", assumptions),
            "caveats": result.get("caveats", []),
            "verdict": result.get("verdict", "ANSWERED"),
        }
    return synthesize_node


def get_nodes(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "decompose": make_decompose_node(config),
        "reason": make_reason_node(config),
        "synthesize": make_synthesize_node(config),
    }
