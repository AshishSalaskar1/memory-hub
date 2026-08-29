# Memory Types

Memory Hub stores durable repository knowledge with provenance. Git answers what changed; session memory explains meaning and rationale.

| Type | Captures | Key rule |
|---|---|---|
| Work | Tasks, outcomes, tests, dependencies, file changes | Separate completed work from intent and incomplete work |
| Decision | Choice, scope, rationale, alternatives, tradeoffs, reconsideration conditions | Brainstorming is `proposed`, not `active` |
| Developer direction | Explicit instruction or correction, importance, scope | Human statements outrank agent interpretations; preserve supersession |
| Architecture | Components, boundaries, data flows, invariants, integrations, debt | Record only durable structure relevant to future work |
| Capability | Product/system behavior, implementation status, files, tests, limitations | `implemented` needs repository evidence |
| Open loop | Unfinished work, blockers, questions, missing tests, deferred refactors, workarounds | Include a concrete next step when known |
| Feedback | Positive notes, corrections, concerns, and suggestions about the repository or stored memory | Preserve the user's statement and target; do not silently rewrite the target |

Architecture memory is expressed through decisions, capabilities, tasks, evidence, and relationships rather than a separate capture array.

## Authority

Use these provenance categories consistently:

| Category | Meaning |
|---|---|
| Observed fact | Verified from Git, a file, a test, or tool output |
| Agent interpretation | Extracted or summarized by the active agent |
| Human-confirmed decision | Explicitly approved by the developer |
| Hypothesis | Plausible but unverified |
| Future intent | Planned behavior, not current behavior |

Authority order is human-confirmed or explicit-human direction, observed evidence, agent interpretation, then hypothesis. Future intent is not evidence of implementation. Higher authority does not erase history: supersede incorrect or outdated records and retain the relationship.

## Capture guidance

- Store concise extracted knowledge, not raw conversation transcripts.
- Prefer repository-relative file paths and stable, specific scopes.
- Attach evidence to consequential claims where available.
- Record alternatives only when they were genuinely considered.
- Record corrections as directions and link or describe what they correct.
- Do not infer rationale from code when it is unknown; mark it unknown or omit it.
- Do not duplicate unchanged memories at every checkpoint unless their status or evidence changed.
- Never store credentials, tokens, private URLs with secrets, personal data without need, or large proprietary excerpts.

## Lifecycle

Tasks and open loops can move through their defined statuses. Decisions and directions are not rewritten in place to hide changed understanding; create a superseding record and link it with `supersedes`. Capabilities may progress from `planned` to `partial` to `implemented`, or become `deprecated`, based on code and test evidence.

A checkpoint preserves current progress inside an open logical session. A close records the final available understanding and closes that session. Neither can reconstruct context the active agent has already lost.

Feedback is user-authored evaluative memory. It may apply to the repository, one session, or one stored memory record. Corrections and concerns should be surfaced prominently during relevant retrieval, but they do not change the target record automatically. The user can edit or delete feedback through the local browser.
