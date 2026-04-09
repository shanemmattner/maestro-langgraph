# Think, Plan, Act, Verify

A step-by-step playbook for the core engineering execution loop. This is the pattern behind the `examples/adaptive/` workflow -- expressed as a process any LLM can follow.

**When to use:** Any task that changes code, config, or infrastructure: features, bug fixes, refactors, migrations.

**Principles:** Maestro #1 (Start Simple), #3 (Closed-Loop Quality), #7 (Adversarial Review).

---

## Prerequisites

- A clear task description (issue, ticket, or user request)
- Access to the codebase (read and write)
- A way to run tests or verify changes (test suite, linter, manual checks)

---

## Steps

### 1. Think -- Understand the task

Read before you write. Gather context until you can explain the task to someone else.

- Read the task description and any linked issues or docs
- Identify the files, modules, and systems involved
- Note constraints: backward compatibility, performance requirements, security implications
- List what you do NOT know and need to find out
- Summarize your understanding in 3-5 sentences

**Output:** A written analysis of what needs to happen and why. This maps to the `prompts/think.txt` phase in the adaptive workflow.

### 2. Plan -- Break into pieces

Decompose the task into small, independently verifiable pieces. Each piece should be completable and testable on its own.

For each piece, define:
- **ID**: A short name (e.g., `1-add-migration`, `2-update-service`)
- **Description**: What to do in one sentence
- **Acceptance criteria**: How to verify it worked -- specific and testable

Order the pieces so dependencies flow forward. No piece should depend on a later piece.

**Output:** A numbered list of pieces with descriptions and acceptance criteria.

### 3. Review the plan -- Adversarial challenge

Before writing any code, get the plan reviewed by a separate session or model. Follow the [adversarial-review.md](./adversarial-review.md) cookbook.

The reviewer should check:
- Is the decomposition too granular or too coarse?
- Are acceptance criteria actually testable?
- Are there missing pieces (error handling, tests, docs)?
- Is the ordering correct?

If the plan is rejected, revise and resubmit. Do not skip this step.

### 4. Act -- Execute each piece

Work through the pieces in order. For each piece:

1. Implement the change
2. Keep the scope tight -- only do what this piece requires
3. Do not refactor adjacent code unless the piece explicitly calls for it
4. If you discover the plan is wrong mid-execution, stop and replan rather than improvising

**Output:** The implemented change for each piece.

### 5. Verify -- Check each piece

After implementing each piece, verify it against its acceptance criteria before moving to the next one.

Verification methods, in order of preference:
1. **Automated tests** -- run the test suite, check for regressions
2. **Static analysis** -- linter, type checker, `py_compile` via `verify.py`
3. **Manual check** -- read the output, inspect the file, test the endpoint
4. **Acceptance criteria check** -- does it satisfy what was defined in step 2?

If verification fails:
- Read the error carefully
- Fix the issue
- Re-verify
- If it fails again after 2 attempts, reconsider whether the piece was correctly defined

**Output:** A pass/fail verdict for each piece with details on what was checked.

### 6. Handle failures

When things go wrong (and they will), follow this escalation:

| Situation | Action |
|-----------|--------|
| Test fails with a clear error | Fix the bug, re-verify |
| Test fails with an unclear error | Re-read the code, add logging, isolate the failure |
| Piece cannot be implemented as planned | Stop. Replan from the current state. Do not force it |
| Multiple pieces are failing | The plan may be wrong. Go back to step 2 |
| Stuck after 3 attempts on the same issue | Escalate to a human with a clear summary of what was tried |

Never silently skip a failing verification. A piece that does not pass verification is not done.

### 7. Wrap up

After all pieces pass verification:
- Run the full test suite to check for cross-piece regressions
- Review the complete diff to make sure nothing unintended crept in
- Commit with a clear message describing what was done and why
- If using tracing, review the trace for any anomalies (stuck loops, excessive retries, budget overruns)

---

## Expected Output

- A task analysis (from step 1)
- A reviewed plan with pieces and acceptance criteria (from steps 2-3)
- Implemented and verified changes (from steps 4-5)
- A final summary: what was done, what was verified, any known issues

---

## Anti-patterns

- **Act without Think**: Jumping to code before understanding the task. Leads to rework.
- **Plan without Review**: Executing a plan nobody challenged. Catches fewer mistakes.
- **Verify at the end**: Implementing all pieces then testing once. Failures compound and are harder to diagnose.
- **Improvise mid-execution**: Discovering the plan is wrong and hacking around it instead of replanning.
- **Silent failures**: A test fails, so you delete the test. The acceptance criteria is wrong, so you weaken it.
