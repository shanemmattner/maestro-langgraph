"""Workflow registry — imports trigger register_workflow() in each package."""

from langgraph_maestro.workflows.adaptive.graph import run_workflow as run_adaptive
from langgraph_maestro.workflows.chain_of_thought.graph import run_workflow as run_chain_of_thought
from langgraph_maestro.workflows.customize.graph import run_workflow as run_customize
from langgraph_maestro.workflows.default.graph import run_workflow as run_default
from langgraph_maestro.workflows.devils_advocate.graph import run_workflow as run_devils_advocate
from langgraph_maestro.workflows.e2e_test.graph import run_workflow as run_e2e_test
from langgraph_maestro.workflows.e2e_test_selector.graph import run_workflow as run_e2e_test_selector
from langgraph_maestro.workflows.issue_to_pr.graph import run_workflow as run_issue_to_pr
from langgraph_maestro.workflows.meta_review.graph import run_workflow as run_meta_review
from langgraph_maestro.workflows.pr_review.graph import run_workflow as run_pr_review

__all__ = [
    "run_adaptive",
    "run_chain_of_thought",
    "run_customize",
    "run_default",
    "run_devils_advocate",
    "run_e2e_test",
    "run_e2e_test_selector",
    "run_issue_to_pr",
    "run_meta_review",
    "run_pr_review",
]
