---
name: memory-hub
description: Capture, retrieve, consolidate, edit, export, and browse durable repository memory. Use when the user invokes /memory-hub or asks to initialize memory, checkpoint or close a coding session, find task-relevant memories, consolidate the store, show memory status, export memory, or manage the local Memory Hub server.
license: MIT
compatibility: Requires Python 3.10+ and Git for full mode. Reduced mode works without script execution; the optional browser binds only to 127.0.0.1.
---

# Memory Hub

Preserve useful repository knowledge, not raw transcripts. SQLite in the current repository's `.memory-hub/` directory is authoritative; Markdown is an export.

## Parse the request

Treat the first word after `/memory-hub` as the action and the remaining text as arguments. Supported actions are:

| User action | Meaning | Script operation |
|---|---|---|
| `init` | Initialize repository memory and cold-start metadata | `init` |
| `checkpoint` | Save progress without ending the logical session | `capture` with `session.mode: checkpoint` |
| `close` | Save progress and close the logical session | `capture` with `session.mode: close` |
| `context [task]` | Retrieve a concise, task-relevant context pack | `context`, optional `--task` |
| `recall <query> [task]` | Search for a small set of memories relevant to a question and current task | `recall`, with query and optional `--task` |
| `dream` | Audit and mechanically consolidate the memory index | `dream`, then `dream --apply` with user approval |
| `feedback` | Interview the user and store feedback about the repository, a session, or a memory | `feedback` with a temporary JSON input |
| `status` | Show repository memory health and counts | `status` |
| `export [target]` | Generate Markdown from SQLite | `export`, forwarding supported target arguments |
| `server` | Start or reuse the localhost browser | `server` |
| `serve` | Alias for `server` | `server` |
| `stop` | Stop the server recorded by Memory Hub | `stop` |

If no action is supplied, infer it only from an unambiguous natural-language request on the following lines. Otherwise list the supported actions and ask which one to run. Do not invent actions. `server` is the documented spelling; accept `serve` only as its alias.

## Select a mode

Use **full mode** when Python 3.10+, Git, and script execution are available. In full mode, use the bundled script for SQLite, Git inspection, retrieval, export, and server lifecycle.

Use **reduced mode** when the script cannot run. State that persistence, verified Git state, retrieval, export from SQLite, and browser actions are unavailable. For `checkpoint` or `close`, produce the schema-version-1 JSON capture and a concise Markdown summary in the conversation; do not claim either was persisted. For all other actions, explain the unavailable capability and the requirement for full mode. Never create an alternative database or treat Markdown as canonical.

## Locate and invoke the script

Resolve `scripts/memory_hub.py` relative to this installed `SKILL.md`, never relative to the user's repository and never via a presumed global executable. Resolve the repository root from the user's working repository and pass it explicitly as an absolute path. Quote all paths and task text.

Invoke exactly:

```bash
python3 "<skill-directory>/scripts/memory_hub.py" init --repo-root "<repository-root>"
python3 "<skill-directory>/scripts/memory_hub.py" capture --repo-root "<repository-root>" --input "<capture-json-path>"
python3 "<skill-directory>/scripts/memory_hub.py" context --repo-root "<repository-root>" --task "<task>"
python3 "<skill-directory>/scripts/memory_hub.py" recall --repo-root "<repository-root>" "<query>" --task "<task>"
python3 "<skill-directory>/scripts/memory_hub.py" dream --repo-root "<repository-root>"
python3 "<skill-directory>/scripts/memory_hub.py" dream --repo-root "<repository-root>" --apply
python3 "<skill-directory>/scripts/memory_hub.py" feedback --repo-root "<repository-root>" --input "<feedback-json-path>"
python3 "<skill-directory>/scripts/memory_hub.py" status --repo-root "<repository-root>"
python3 "<skill-directory>/scripts/memory_hub.py" export --repo-root "<repository-root>"
python3 "<skill-directory>/scripts/memory_hub.py" server --repo-root "<repository-root>"
python3 "<skill-directory>/scripts/memory_hub.py" stop --repo-root "<repository-root>"
```

Omit `--task` when `context` has no task. For `export decisions` and `export session <id>`, append those user-supplied target arguments after `--repo-root "<repository-root>"` if supported by the installed script; otherwise report that the installed version supports only the full export. The temporary capture file must be outside `.memory-hub/`, contain only the validated JSON object, and be removed after the script returns. Do not ask the user to run internal commands.

If `python3` is unavailable but a verified Python 3.10+ interpreter is available as `python`, substitute only the interpreter token.

## Responsibilities

The **agent** parses intent, summarizes context it currently has, distinguishes facts from interpretations, extracts tasks, decisions, directions, changes, capabilities, open work, evidence, and relationships, proposes confidence and confirmation states, asks focused confirmation questions, and explains retrieved memory.

The **script** discovers and validates repository state, initializes and migrates SQLite, records timestamps and Git facts, validates capture JSON, stores and queries records, exports Markdown, manages the localhost server and its PID/port state, and enforces integrity.

Do not fabricate Git facts, timestamps, IDs, or persistence. Do not read proprietary agent session databases. Memory Hub cannot recover context already lost unless it was previously captured.

## Run actions

### `init`

Run `init` in full mode. Describe cold-start claims as observed, inferred, or unknown; repository evidence cannot recover historical rationale. Mention `.gitignore` treatment only as a suggestion unless the user asks to change it.

### `checkpoint` and `close`

Review available session context and prepare the schema in [references/capture-schema.md](references/capture-schema.md). Set `session.mode` to `checkpoint` or `close` exactly. Include every applicable entity array, using empty arrays when none apply. Git remains the authority for files, branch, commits, and tests visible to tools.

Before persistence, show a short summary of important decisions, developer directions, and uncertain claims. Ask for confirmation when a claim is consequential and inferred, when intent is ambiguous, or when a direction/decision would be recorded as human-confirmed without explicit evidence. Offer `save`, `edit`, or `cancel`. Explicit statements already made by the user need no redundant confirmation; record their provenance accurately. Routine observed changes and low-risk progress may be saved without confirmation. Never label agent inference as human-confirmed.

After confirmation when required, write the temporary JSON and run `capture`. A checkpoint keeps the logical session open; close marks it closed. Report what was stored and any validation warnings without dumping the full payload unless requested.

### `context`

Run `context` with the supplied task text. Return a concise pack prioritizing task-relevant active decisions, human-confirmed directions, capabilities, relevant files, and open work. Do not inject every session or exceed the useful context budget.

Use `context <task>` once near the beginning of substantial work to establish broad current state. During implementation, use `recall` for narrow questions instead of repeatedly loading the broad context pack.

### `recall`

Run `recall` when the user or current task raises a specific historical question, such as why a design was chosen, which files implement a capability, or whether a developer direction applies. Pass the question as the query and the active work as `--task` when available. Return only the highest-ranked matches with their stable IDs, types, statuses, and concise summaries. Do not fetch all memories first and do not answer from a full database dump.

Agents should retrieve incrementally: start work with `context <task>`, call `recall <specific question> --task <current task>` when a decision point arises, and inspect the cited records rather than loading unrelated sessions.

### `dream`

Run `dream` first without `--apply`. It audits the store, reports exact duplicate candidates and dangling references, and previews mechanical repairs. Show the report to the user and request approval before running `dream --apply`.

Applied dreaming rebuilds the search index and repairs only unambiguous reciprocal supersession links and statuses. It must not merge similar memories, delete history, invent conclusions, alter human authority, or reinterpret semantic content. Duplicate candidates and ambiguous problems remain review items for a human.

### `feedback`

Treat feedback as a conversational workflow, not a request for a free-form dump. Ask one concise question at a time and wait for the answer before continuing. Do not present the entire questionnaire in one message.

Collect these fields:

1. Type: `positive`, `correction`, `concern`, or `suggestion`.
2. Scope: `repository`, `session`, or `record`.
3. Target: for session scope, identify the session; for record scope, identify the memory record. Use `status`, `context`, `recall`, or the browser to help the user find an ID instead of guessing.
4. Feedback body: ask what happened, what should remain true, or what should change.
5. Sentiment: `positive`, `neutral`, or `negative`.
6. Optional rating: integer `1` through `5`; omission means no rating.

After collecting the answers, summarize the proposed feedback in a compact confirmation and offer `save`, `edit`, or `cancel`. On save, write only the standalone feedback JSON described in [references/capture-schema.md](references/capture-schema.md) to a temporary file outside `.memory-hub/`, invoke the `feedback` operation, and remove the temporary file. Feedback informs future `context` and `recall` results but does not automatically rewrite or supersede its target.

In reduced mode, return the structured feedback JSON in the conversation and state that it was not persisted.

### `status`, `export`, `server`, and `stop`

Run the matching operation. Exports are generated views and must not be presented as database input. Report the server URL exactly as returned; it must use `127.0.0.1`. Reuse a healthy existing server. Stop only the process identified by `.memory-hub/server.json`, never an arbitrary matching process.

## Fail safely

On validation failure, do not retry with fields removed silently. Report the failing field and expected contract, correct only what can be established, and ask about semantic ambiguity. On missing initialization, offer or run `init` only with user approval before the requested mutating action. On missing dependencies or denied execution, switch to reduced mode and say what was not persisted.

On script, Git, database, export, or server failure, preserve the user's source data, report the command operation and actionable error, and do not claim success. Never edit exported Markdown to simulate persistence, delete or replace a database, kill an unverified process, expose the server beyond localhost, or store suspected secrets. If capture content may contain a credential, redact it and ask the user before storing the surrounding memory.

For detailed semantics and workflows, read [references/memory-types.md](references/memory-types.md) and [references/workflows.md](references/workflows.md) only as needed.
