"""Retrieve node — retrieves relevant chunks for a query."""

import logging
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config, get_models_for_phase
from langgraph_maestro.core.llm import call_llm_with_fallback, extract_json

logger = logging.getLogger(__name__)

# Default parameters
DEFAULT_TOP_K = 5
MAX_CHARS_PER_CHUNK = 2000


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def _score_chunks_llm(query: str, chunks: list[dict], prompt: str, models: list, config: dict) -> list[dict]:
    """Score and rank chunks using LLM."""
    truncated = []
    for chunk in chunks:
        content = chunk.get("content", "")
        if len(content) > MAX_CHARS_PER_CHUNK:
            content = content[:MAX_CHARS_PER_CHUNK] + "..."
        truncated.append({
            "chunk_id": chunk.get("chunk_id", ""),
            "path": chunk.get("path", ""),
            "content": content,
        })

    import json as _json
    prompt_filled = prompt.replace("{query}", query).replace("{chunks}", _json.dumps(truncated, indent=2))

    result = call_llm_with_fallback(
        prompt=prompt_filled,
        models=models,
        phase="retrieve",
        config=config,
        system_prompt="You are a document retriever. Return valid JSON only.",
    )
    parsed = extract_json(result.get("content", ""))

    if not parsed:
        # Fallback: return top-k by order
        return [{"chunk_id": c.get("chunk_id"), "score": 1.0 / (i + 1)} for i, c in enumerate(chunks[:DEFAULT_TOP_K])]

    # Map scores back to chunks
    scored = []
    for item in parsed:
        chunk_id = item.get("chunk_id")
        score = item.get("relevance_score", 0.0)
        # Find the corresponding chunk
        for chunk in chunks:
            if chunk.get("chunk_id") == chunk_id:
                scored.append({
                    "chunk_id": chunk_id,
                    "path": chunk.get("path", ""),
                    "content": chunk.get("content", ""),
                    "score": score,
                })
                break

    # Sort by score descending
    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return scored


def _score_chunks_keyword(query: str, chunks: list[dict], top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Simple keyword-based scoring (fallback)."""
    query_terms = set(query.lower().split())

    scored = []
    for chunk in chunks:
        content = chunk.get("content", "").lower()
        path = chunk.get("path", "").lower()

        # Count matching terms
        matches = sum(1 for term in query_terms if term in content or term in path)

        scored.append({
            "chunk_id": chunk.get("chunk_id"),
            "path": chunk.get("path", ""),
            "content": chunk.get("content", ""),
            "score": matches,
        })

    # Sort by score descending
    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return scored[:top_k]


def make_retrieve_node(
    config_path_default: str = str(Path(__file__).parent.parent / "workflows" / "doc_qa" / "config.yaml"),
    prompts_dir: str = str(Path(__file__).parent.parent / "workflows" / "doc_qa" / "prompts"),
) -> Callable[[dict], dict]:
    """Create a retrieve node that finds relevant chunks for a query.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory

    Returns:
        A node function that retrieves relevant chunks
    """
    prompts_path = Path(prompts_dir)
    prompt_template = _load_prompt("retriever", prompts_path)

    def retrieve_node(state: dict) -> dict:
        """Retrieve relevant chunks for the query."""
        start = time.time()
        query = state.get("query", "")
        chunks = state.get("chunks", [])
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)

        retrieve_config = config.get("retrieve", {})
        use_llm = retrieve_config.get("use_llm", True)
        top_k = retrieve_config.get("top_k", DEFAULT_TOP_K)
        models = get_models_for_phase("retrieve", config)

        logger.info("retrieve_start", extra={"query": query, "chunks_total": len(chunks)})

        if not chunks:
            return {
                "retrieved_chunks": [],
                "phase": "retrieve",
            }

        if not query:
            return {
                "retrieved_chunks": [],
                "phase": "retrieve",
            }

        if use_llm and prompt_template:
            try:
                scored_chunks = _score_chunks_llm(query, chunks, prompt_template, models, config)
            except Exception as e:
                logger.warning("llm_retrieve_failed", extra={"error": str(e)})
                scored_chunks = _score_chunks_keyword(query, chunks, top_k)
        else:
            # Use keyword fallback
            scored_chunks = _score_chunks_keyword(query, chunks, top_k)

        # Take top-k
        retrieved = scored_chunks[:top_k]

        elapsed = round(time.time() - start, 3)
        logger.info(
            "retrieve_done",
            extra={
                "retrieved_count": len(retrieved),
                "elapsed": elapsed,
            },
        )

        return {
            "retrieved_chunks": retrieved,
            "phase": "retrieve",
        }

    return retrieve_node
