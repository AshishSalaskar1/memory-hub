# Capture Workflow

Use for `checkpoint` and `close` only.

1. Review available conversation context; never inspect proprietary session stores.
2. Extract only durable tasks, decisions, directions, capabilities, open work, evidence, and relationships. Avoid duplicate unchanged memories.
3. Build the sparse schema-v1 payload described in [capture-schema.md](capture-schema.md). Omit empty entity arrays and routine provenance fields. Omit `changes` to let the script derive working-tree changes from Git; include it only when adding meaningful semantic summaries.
4. Set `session.mode` exactly to `checkpoint` or `close`. A checkpoint keeps the logical session open; close finalizes it.
5. Show a compact summary and request `save`, `edit`, or `cancel` only for consequential inference, ambiguous intent, a claim marked human-confirmed without explicit evidence, or sensitive-looking content after redaction. Explicit user statements and routine observed facts need no redundant confirmation.
6. On save, write JSON to a temporary file outside `.memory-hub/`, run `capture --input`, remove the file, and report stored counts and warnings.

Git is authoritative for branch, commits, changed files, and tests visible to tools. Never label agent inference as human-confirmed. On validation failure, report the field and contract; do not silently remove data to force acceptance.
