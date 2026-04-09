"""Chain-of-thought workflow: decompose -> reason -> synthesize."""
from typing import Any, Dict

from langgraph.graph import StateGraph, END

from langgraph_maestro.core.runner import run_workflow as core_run_workflow
from langgraph_maestro.core.checkpointer import get_checkpointer
from .nodes import get_nodes
from .state import ChainOfThoughtState


def build_graph():
    nodes = get_nodes()

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
) -> Dict[str, Any]:
    graph = build_graph()

    initial_state = {
        "question": question,
        "context": context or "none",
        "domain": domain,
        "sub_questions": [],
        "assumptions": [],
        "reasoning_steps": [],
        "step_errors": [],
    }
    thread_id = f"cot-{hash(question) & 0xFFFFFFFF:08x}"
    return core_run_workflow("chain_of_thought", graph, initial_state, thread_id)
