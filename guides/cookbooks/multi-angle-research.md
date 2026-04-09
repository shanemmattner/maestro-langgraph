# Multi-Angle Research

A step-by-step playbook for researching a topic from multiple perspectives, grounding findings with sources, and producing a synthesis that accounts for contradictions.

**When to use:** Before making a technology choice, entering a new domain, evaluating a vendor, or answering any question where a single perspective would be dangerously incomplete.

**Principle:** Maestro #4 -- "Ground claims with web search, file reads, or tool output. Never hallucinate facts."

---

## Prerequisites

- A clear research question or decision to be made
- Access to web search (SearXNG via `web.py`, or any search tool)
- Optionally, multiple LLM sessions to run perspectives in parallel

---

## Steps

### 1. Define the research question

Write the question in one sentence. Then list 2-3 specific sub-questions that would need answers before you could make a decision.

Example:
- **Question**: Should we use SQLite or Postgres for our embedded analytics feature?
- **Sub-questions**: What are the concurrency limits of SQLite? What is the ops burden of embedded Postgres? Are there hybrid approaches?

### 2. Assign research angles

Launch separate research threads from each of these perspectives. Each angle should produce its own findings independently.

| Angle | Focus | Example prompts |
|-------|-------|----------------|
| **Technical** | Capabilities, limitations, architecture fit | "What are the technical tradeoffs of X vs Y for our constraints?" |
| **Business** | Cost, licensing, vendor risk, time-to-market | "What are the total cost of ownership and licensing implications?" |
| **Competitive** | What do similar products or teams use? | "What do companies in our space use for this? What went wrong?" |
| **User** | Impact on end-user experience, migration pain | "How does this choice affect latency, reliability, or UX?" |
| **Contrarian** | Argue against the obvious choice | "What is the strongest case AGAINST the option we are leaning toward?" |

You do not need all five angles for every question. Pick the ones that matter. The contrarian angle is always worth including.

### 3. Ground every claim with a source

For each angle, use web search to find concrete evidence. Every factual claim must link to a source: documentation, benchmark, case study, or post-mortem.

If using `web.py`:
- Search for recent results (filter to the last 1-2 years when relevance decays quickly)
- Scrape the actual page content rather than trusting search snippets
- Prefer primary sources (official docs, benchmarks) over secondary (blog summaries)

If a claim cannot be sourced, label it as **unverified assumption**.

### 4. Synthesize across perspectives

After all angles report back, produce a single synthesis document:

```
## Research Summary: [Question]

### Key Findings
- [Finding 1] -- supported by [Technical] and [Competitive] angles
- [Finding 2] -- [Business] angle raises concern, [Technical] disagrees

### Contradictions
- [Angle A] says X, but [Angle B] says Y. Resolution: [your analysis]

### Gaps
- [What we still do not know and how to find out]

### Recommendation
[Your recommendation with reasoning. State confidence level: high/medium/low]

### Sources
- [Numbered list of all sources cited]
```

### 5. Identify gaps and next steps

List what the research did NOT answer. For each gap, suggest how to close it:
- Run a proof-of-concept
- Talk to a domain expert
- Read a specific paper or doc
- Run a benchmark

### 6. Get the synthesis reviewed

Pass the synthesis through an adversarial review (see [adversarial-review.md](./adversarial-review.md)). The reviewer should check:
- Are sources actually saying what the synthesis claims?
- Are contradictions acknowledged or swept under the rug?
- Is the recommendation supported by the evidence or by bias?

---

## Expected Output

A research summary document containing:

- 3-5 key findings with source citations
- Contradictions between perspectives and how they were resolved
- Known gaps with suggested next steps
- A recommendation with stated confidence level
- A numbered source list

---

## Anti-patterns

- **Single-angle research**: Only looking at the technical perspective and ignoring business or user impact.
- **Source-free claims**: "X is faster than Y" with no benchmark or documentation link.
- **Confirmation bias**: All angles happen to agree because the prompts were leading. The contrarian angle exists to prevent this.
- **Stale sources**: Citing a 2019 blog post for a technology that shipped a major rewrite in 2024.
