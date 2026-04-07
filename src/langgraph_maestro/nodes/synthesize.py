"""Synthesize node — generates final answer from retrieved chunks."""

import logging
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)

MAX_CONTEXT_TOKENS = 12000


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def _build_context(retrieved_chunks: list[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    """Build context string from retrieved chunks."""
    context_parts = []
    current_chars = 0
    max_chars = max_tokens * 4  # rough: 4 chars per token

    for chunk in retrieved_chunks:
        path = chunk.get("path", "unknown")
        content = chunk.get("content", "")

        part = f"--- Source: {path} ---\n{content}\n"
        if current_chars + len(part) > max_chars:
            break
        context_parts.append(part)
        current_chars += len(part)

    return "\n".join(context_parts)


def make_synthesize_node(
    config_path_default: str = str(Path(__file__).parent.parent / "workflows" / "doc_qa" / "config.yaml"),
    prompts_dir: str = str(Path(__file__).parent.parent / "workflows" / "doc_qa" / "prompts"),
) -> Callable[[dict], dict]:
    """Create a synthesize node that generates answer from retrieved chunks.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory

    Returns:
        A node function that synthesizes answer from chunks
    """
    prompts_path = Path(prompts_dir)
    prompt_template = _load_prompt("synthesizer", prompts_path)

    def synthesize_node(state: dict) -> dict:
        """Synthesize answer from retrieved chunks."""
        start = time.time()
        query = state.get("query", "")
        retrieved_chunks = state.get("retrieved_chunks", [])
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)

        models = get_models_for_phase("synthesize", config)

        logger.info("synthesize_start", extra={"query": query, "chunks": len(retrieved_chunks)})

        if not retrieved_chunks:
            answer = "No relevant documents found to answer the query."
            return {
                "answer": answer,
                "sources": [],
                "phase": "synthesize",
            }

        if not query:
            answer = "No query provided."
            return {
                "answer": answer,
                "sources": [],
                "phase": "synthesize",
            }

        # Build context from retrieved chunks
        context = _build_context(retrieved_chunks)

        # Build the prompt
        if prompt_template:
            prompt_filled = prompt_template.format(
                query=query,
                context=context,
            )
        else:
            # Default prompt
            prompt_filled = f"""Use the following context to answer the question.

Question: {query}

Context:
{context}

Answer:"""

        try:
            result = call_llm_with_fallback(
                prompt=prompt_filled,
                models=models,
                phase="synthesize",
                config=config,
                system_prompt="You are a document analyst. Answer questions from document context. Return valid JSON with fields: answer, sources (list of file paths), confidence (0.0-1.0), verdict (ANSWER|PARTIAL|NO_ANSWER).",
            )
            content = result.get("content", "")
            parsed = extract_json(content)
            if parsed:
                answer = parsed.get("answer", content)
                cited_sources = parsed.get("sources", [])
                confidence = parsed.get("confidence", 0.8)
                verdict = parsed.get("verdict", "ANSWER")
            else:
                answer = content
                cited_sources = []
                confidence = 0.5
                verdict = "PARTIAL"
        except Exception as e:
            logger.error("synthesize_failed", extra={"error": str(e)})
            answer = f"Error generating answer: {e}"
            cited_sources = []
            confidence = 0.0
            verdict = "NO_ANSWER"

        sources = cited_sources or list(set(chunk.get("path", "") for chunk in retrieved_chunks))

        elapsed = round(time.time() - start, 3)
        logger.info(
            "synthesize_done",
            extra={"answer_length": len(answer), "sources_count": len(sources), "elapsed": elapsed},
        )

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
            "verdict": verdict,
            "phase": "synthesize",
        }

    return synthesize_node
