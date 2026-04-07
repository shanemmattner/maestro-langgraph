"""Checkpointer factory for durable workflow state.

Provides crash-safe checkpointing via SQLite (default) with fallback to
in-memory for testing.
"""

import os
import sqlite3
from pathlib import Path


def get_checkpointer(backend: str = "auto"):
    """Get a checkpointer instance.

    Args:
        backend: 'auto' or 'sqlite' for durable SQLite checkpointing,
                 'memory' for in-memory (testing only).

    Returns:
        A LangGraph checkpointer instance.
    """
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    # auto / sqlite → SqliteSaver with direct connection
    db_dir = Path(os.environ.get(
        "LANGGRAPH_CHECKPOINT_DIR",
        Path.home() / ".cache" / "langgraph-maestro",
    ))
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "checkpoints.db"

    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)
