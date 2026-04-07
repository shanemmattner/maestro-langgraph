"""Devil's Advocate workflow state — adversarial design review."""

from typing import TypedDict


class CounterEvidence(TypedDict, total=False):
    source: str
    argument: str
    severity: str  # HIGH | MEDIUM | LOW


class Alternative(TypedDict, total=False):
    approach: str
    evidence: str
    tradeoffs: str


class DevilsAdvocateState(TypedDict, total=False):
    # Input
    proposal: str
    proposal_type: str  # pricing | architecture | positioning | features | go-to-market
    context_path: str  # optional path to docs for additional context
    config_path: str

    # Phase: research_counter_evidence
    counter_evidence: list[CounterEvidence]

    # Phase: find_alternatives
    alternatives: list[Alternative]

    # Phase: build_critique
    critique: str  # structured adversarial argument

    # Phase: defend_proposal
    defense: str  # rebuttal defending the proposal

    # Phase: judge_verdict
    verdict: str  # PROCEED | REVISE | ABANDON
    confidence_score: float  # 0.0 - 1.0

    # Phase: write_report
    report_path: str

    # Control flow
    phase: str
    errors: list[str]
