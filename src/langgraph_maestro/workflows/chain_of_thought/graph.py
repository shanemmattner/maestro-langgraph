"""Chain-of-thought workflow: decompose → reason → synthesize."""
from typing import Any, Dict

from langgraph.graph import StateGraph, END

from langgraph_maestro.core.runner import run_workflow as core_run_workflow
from langgraph_maestro.workflows.chain_of_thought.nodes import get_nodes
from langgraph_maestro.workflows.chain_of_thought.state import ChainOfThoughtState
from langgraph_maestro.core.config import workflow_config_path


def build_graph(config_path: str = workflow_config_path(__file__)):
    from langgraph_maestro.core.checkpointer import get_checkpointer
    from langgraph_maestro.core.config import load_config

    config = load_config(config_path) if config_path else {}
    nodes = get_nodes(config)

    workflow = StateGraph(ChainOfThoughtState)
    workflow.add_node("decompose", nodes["decompose"])
    workflow.add_node("reason", nodes["reason"])
    workflow.add_node("synthesize", nodes["synthesize"])

    workflow.set_entry_point("decompose")
    workflow.add_edge("decompose", "reason")
    workflow.add_edge("reason", "synthesize")
    workflow.add_edge("synthesize", END)

    return workflow.compile(checkpointer=get_checkpointer())


def run_workflow(
    question: str,
    context: str = "",
    domain: str = "general",
    config_path: str = workflow_config_path(__file__),
) -> Dict[str, Any]:
    graph = build_graph(config_path)

    initial_state = {
        "question": question,
        "context": context or "none",
        "domain": domain,
        "sub_questions": [],
        "assumptions": [],
        "reasoning_steps": [],
        "step_errors": [],
        "config_path": config_path,
    }
    thread_id = f"cot-{hash(question) & 0xFFFFFFFF:08x}"
    return core_run_workflow("chain_of_thought", graph, initial_state, thread_id)
