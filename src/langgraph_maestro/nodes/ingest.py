"""Ingest node — loads documents and chunks them."""

import logging
import os
import time
from pathlib import Path
from typing import Callable

from langgraph_maestro.core.config import load_config

logger = logging.getLogger(__name__)

# File extensions to include when scanning directories
ALLOWED_EXTENSIONS = {".py", ".md", ".txt", ".yaml", ".yml", ".json"}

# Skip files larger than 100KB
MAX_FILE_SIZE = 100 * 1024

# Chunking parameters
TARGET_TOKENS = 500
OVERLAP_TOKENS = 50


def _load_prompt(name: str, prompts_dir: Path) -> str:
    """Load a prompt template from the prompts directory."""
    path = prompts_dir / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def _find_files(paths: list[str]) -> list[Path]:
    """Find all allowed files in the given paths (files or directories)."""
    files = []
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning("path_not_found", extra={"path": str(path)})
            continue
        if path.is_file():
            if path.suffix in ALLOWED_EXTENSIONS and path.stat().st_size <= MAX_FILE_SIZE:
                files.append(path)
        elif path.is_dir():
            for root, _, filenames in os.walk(path):
                for filename in filenames:
                    file_path = Path(root) / filename
                    if file_path.suffix in ALLOWED_EXTENSIONS and file_path.stat().st_size <= MAX_FILE_SIZE:
                        files.append(file_path)
    return files


def _chunk_text(text: str, chunk_id_prefix: str) -> list[dict]:
    """Chunk text by paragraphs/sections (simple approach)."""
    if not text.strip():
        return []

    # Split by double newlines (paragraphs)
    paragraphs = text.split("\n\n")
    chunks = []
    chunk_id = 0

    current_chunk = ""
    current_tokens = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Estimate tokens (rough: 4 chars per token)
        para_tokens = len(para) // 4

        # If adding this paragraph exceeds target, start a new chunk
        if current_tokens + para_tokens > TARGET_TOKENS and current_chunk:
            chunks.append({
                "chunk_id": f"{chunk_id_prefix}_{chunk_id}",
                "content": current_chunk.strip(),
            })
            chunk_id += 1

            # Start new chunk with overlap
            overlap_lines = current_chunk.strip().split("\n")
            if len(overlap_lines) > 2:
                current_chunk = "\n\n".join(overlap_lines[-2:]) + "\n\n" + para
            else:
                current_chunk = para
            current_tokens = len(current_chunk) // 4
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
            current_tokens += para_tokens

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "chunk_id": f"{chunk_id_prefix}_{chunk_id}",
            "content": current_chunk.strip(),
        })

    return chunks


def _read_file(path: Path) -> str | None:
    """Read file content, return None if error."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("file_read_error", extra={"path": str(path), "error": str(e)})
        return None


def make_ingest_node(
    config_path_default: str = str(Path(__file__).parent.parent / "workflows" / "doc_qa" / "config.yaml"),
    prompts_dir: str = str(Path(__file__).parent.parent / "workflows" / "doc_qa" / "prompts"),
) -> Callable[[dict], dict]:
    """Create an ingest node that loads and chunks documents.

    Args:
        config_path_default: Default path to the config file
        prompts_dir: Path to the prompts directory

    Returns:
        A node function that loads documents and creates chunks
    """
    prompts_path = Path(prompts_dir)

    def ingest_node(state: dict) -> dict:
        """Load documents from doc_paths and create chunks."""
        start = time.time()
        doc_paths = state.get("doc_paths", [])
        config_path = state.get("config_path", config_path_default)
        config = load_config(config_path)

        logger.info("ingest_start", extra={"doc_paths": doc_paths})

        # Find all files
        files = _find_files(doc_paths)
        logger.info("files_found", extra={"count": len(files)})

        # Read files and create documents
        documents = []
        for file_path in files:
            content = _read_file(file_path)
            if content is None:
                continue

            # Create a document entry
            documents.append({
                "path": str(file_path),
                "content": content,
                "chunk_id": f"doc_{len(documents)}",
            })

        # Chunk each document
        all_chunks = []
        for doc in documents:
            path = doc["path"]
            content = doc["content"]
            base_chunk_id = doc["chunk_id"]

            # Chunk by paragraphs
            chunks = _chunk_text(content, base_chunk_id)

            # Add path to each chunk
            for chunk in chunks:
                chunk["path"] = path

            all_chunks.extend(chunks)

        elapsed = round(time.time() - start, 3)
        logger.info(
            "ingest_done",
            extra={
                "doc_count": len(documents),
                "chunk_count": len(all_chunks),
                "elapsed": elapsed,
            },
        )

        return {
            "documents": documents,
            "chunks": all_chunks,
            "phase": "ingest",
        }

    return ingest_node
