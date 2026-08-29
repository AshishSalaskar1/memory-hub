# Workflows

These workflows separate semantic extraction by the agent from deterministic work by `scripts/memory_hub.py`.

## Initialize

1. Detect full or reduced mode and resolve the repository root.
2. In full mode, run `init` with the absolute repository root.
3. Let the script create/migrate `.memory-hub/memory.db`, configuration, and initial Git metadata.
4. Describe cold-start knowledge as observed, inferred, or unknown. Do not invent historical rationale.
5. Report the initialized path and any script warnings. Suggest ignore rules without changing them unless asked.

## Checkpoint or close

1. Review only context available to the active agent; do not inspect proprietary session stores.
2. Extract completed and open tasks, decisions and rationale, developer directions/corrections, file changes, capability changes, evidence, and relationships.
3. Verify objective repository facts with tools in full mode.
4. Build schema version 1 with every entity array present. Set `session.mode` exactly to `checkpoint` or `close`.
5. Redact suspected secrets. Show consequential memories and uncertain claims; request `save`, `edit`, or `cancel` when confirmation is required.
6. In full mode, place JSON in a temporary file, run `capture --input`, then remove the temporary file. Report persisted counts and warnings.
7. In reduced mode, return JSON and concise Markdown only, clearly marked not persisted.

Checkpoint leaves the logical session open and should preserve continuation context. Close finalizes it. Multiple checkpoints may belong to the same session; avoid duplicating memories that have not changed.

## Retrieve context

1. Use the user's remaining text as the task query; do not rewrite its intent.
2. Run `context`, including `--task` only when task text exists.
3. Present a bounded context pack: current state, relevant active decisions, human-confirmed directions, capabilities/files, and open work.
4. Prefer relevance, recency, active status, and human authority. Do not dump all sessions.

## Recall on demand

Use `recall` for a focused question that arises while working. Pass the narrow query and, when available, the current task. Present only the best matches and retain their stable IDs so the user or agent can inspect, edit, or cite them. Prefer this incremental retrieval over loading complete sessions or all repository memory.

Recommended agent pattern:

1. Run `context --task` once when beginning substantial work.
2. Continue using repository files and tools normally.
3. Run `recall` only when a design choice, developer preference, capability, open loop, or prior change becomes relevant.
4. Treat human-confirmed active memories as higher authority than agent-inferred records.
5. Ignore superseded records unless historical reasoning is explicitly requested.

## Dream

Run `dream` without `--apply` to audit consolidation opportunities. It may identify duplicate candidates and dangling references, preview repairs, and report search-index state. Ask before applying changes.

`dream --apply` may rebuild search indexes and repair mechanically provable supersession links or statuses. It must not merge records based on semantic similarity, delete history, invent rationale, or change provenance and confirmation. Report unresolved items for human review.

## Feedback

When the user invokes `feedback`, conduct a short interview one question at a time:

1. Ask whether the feedback is positive, a correction, a concern, or a suggestion.
2. Ask whether it applies to the repository, a session, or a specific memory record.
3. If scoped to a session or record, help identify the target from current context or a focused lookup. Never guess an ID.
4. Ask for the feedback itself.
5. Ask for positive, neutral, or negative sentiment.
6. Ask whether the user wants to add an optional 1-5 rating.
7. Summarize the structured feedback and ask the user to save, edit, or cancel.
8. On save, write the standalone feedback JSON to a temporary file, invoke `feedback --input`, remove the temporary file, and report the stable feedback ID.

Do not add feedback to a session capture payload. Feedback has its own input contract and can be created at any time. It contributes to task context and recall ranking, especially corrections and suggestions, but never silently mutates the memory it references.

## Status and export

For `status`, report repository identity, sessions, last capture, active decisions, open items, unconfirmed memories, and database path when returned by the script. Do not derive fake counts after a failure.

For `export`, invoke the script and report generated paths. SQLite remains authoritative; edits to `.memory-hub/exports/` do not update it. Forward supported `decisions` or `session <id>` targets, otherwise explain the installed script's supported scope.

## Server lifecycle

For `server` or `serve`, invoke the `server` operation. It must bind to `127.0.0.1`, choose an available port, return promptly, record PID and port in `.memory-hub/server.json`, and reuse a healthy existing server. Return the exact local URL.

For `stop`, invoke `stop`; it may terminate only the process validated from `.memory-hub/server.json`. If state is stale, report it and let the script clean it safely. Never search for and kill arbitrary Python or HTTP processes.

## Confirmation rules

Confirmation is required before storing an important inferred decision, ambiguous developer intent, a claim marked human-confirmed without an explicit statement, or sensitive-looking content after redaction. Confirmation is not required for already explicit user statements, routine observed Git facts, or low-risk progress summaries. Respect cancellation without writing.

## Failure rules

- Missing initialization: request approval to initialize before a mutating action; never silently create a store.
- Invalid capture: name the exact field and expected value; preserve the source capture and do not discard fields to force acceptance.
- Missing Python/Git or denied execution: enter reduced mode and state which functions are unavailable.
- Database/migration error: stop; do not delete, replace, or manually rewrite the database.
- Git error: distinguish unverified semantic capture from objective Git facts and do not fabricate the latter.
- Export error: leave SQLite unchanged and do not hand-edit exports as a substitute.
- Server error: report the actionable error; never bind beyond localhost or kill an unverified process.
- Any operation failure: do not claim persistence or success.
