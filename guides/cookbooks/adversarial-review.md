# Adversarial Review

A step-by-step playbook for critically reviewing any plan, design, or implementation before committing to it. The reviewer must operate in a separate context from the author.

**When to use:** Before executing any non-trivial plan, merging a design doc, or shipping an implementation. The higher the cost of getting it wrong, the more you need this.

**Principle:** Maestro #7 -- "Always have a second agent challenge the plan before executing. The session that wrote it must never review it."

---

## Prerequisites

- A concrete artifact to review (plan, code, design doc, PR, architecture proposal)
- Access to a second LLM session or a different model -- the reviewer must NOT share context with the author
- The original task description or requirements that the artifact is supposed to satisfy

---

## Steps

### 1. Package the artifact for review

Collect everything the reviewer needs into a single, self-contained prompt. Include:

- **The task or goal** -- what problem is being solved
- **The artifact** -- the full plan, code, or design doc
- **Constraints** -- budget, timeline, technical limitations, non-negotiables
- **Context** -- relevant background the reviewer would not otherwise know

Do NOT include the author's reasoning or justification. The reviewer should evaluate the artifact on its own merits.

### 2. Set up the reviewer in a fresh context

Open a new LLM session. Use a different model if possible (e.g., if the author used Sonnet, review with Opus or o3). The reviewer must have zero shared history with the authoring session.

Load the reviewer with this framing:

> You are a critical reviewer. Your job is to find problems with this artifact BEFORE resources are committed. Be harsh but constructive. If it is good enough, say so.

### 3. Run the review against these criteria

Instruct the reviewer to evaluate against each of these dimensions:

| Dimension | What to look for |
|-----------|-----------------|
| **Overcomplicated** | Could this be simpler? Are there unnecessary abstractions, extra steps, or premature optimization? |
| **Missing edge cases** | What happens when inputs are empty, malformed, huge, or concurrent? What if a dependency fails? |
| **Assumptions** | What is being assumed that has not been verified? Are there unstated dependencies? |
| **Security** | Does this expose secrets, create injection vectors, or skip auth checks? |
| **Ordering and dependencies** | Are steps in the right order? Are dependencies between pieces handled? |
| **Testability** | Can each piece be verified independently? Are acceptance criteria clear and measurable? |
| **Alternatives** | Is there a simpler approach that was not considered? |

### 4. Require a structured verdict

Ask the reviewer to respond with:

- **Approved** or **Rejected**
- **Blocking issues** -- problems that must be fixed before proceeding
- **Warnings** -- concerns that should be addressed but are not dealbreakers
- **Suggestions** -- optional improvements

### 5. Synthesize and decide

If **approved with no blocking issues**: proceed to execution.

If **rejected or has blocking issues**:
1. Address each blocking issue in the original artifact
2. Re-submit the revised artifact for another review round
3. Limit to 3 review rounds -- if it still has blocking issues after 3 rounds, escalate to a human

If **approved with warnings**: proceed, but track the warnings as known risks.

### 6. Record the review

Save the review output alongside the artifact. Future sessions benefit from knowing what was challenged and why it was approved. If using tracing (e.g., Langfuse via `tracing.py`), tag the review span so it is searchable.

---

## Expected Output

A review document containing:

- The verdict (approved/rejected)
- A list of blocking issues, warnings, and suggestions
- The final version of the artifact with issues addressed
- A record of how many review rounds were needed

---

## Anti-patterns

- **Self-review**: The session that authored the artifact reviews it. This always rubber-stamps.
- **Review without context**: The reviewer lacks the task description or constraints and critiques in a vacuum.
- **Infinite review loops**: More than 3 rounds means the plan is fundamentally flawed. Replan from scratch.
- **Ignoring warnings**: Approved-with-warnings does not mean warnings are irrelevant. Track them.
