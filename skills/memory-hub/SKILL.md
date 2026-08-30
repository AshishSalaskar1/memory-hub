---
name: memory-hub
description: Capture, retrieve, consolidate, edit, export, and browse durable repository memory. Use when the user invokes /memory-hub or asks to initialize memory, checkpoint or close a coding session, find task-relevant memories, consolidate the store, show memory status, export memory, or manage the local Memory Hub server.
license: MIT
compatibility: Requires Python 3.10+ and Git for full mode. Reduced mode works without script execution; the optional browser binds only to 127.0.0.1.
---

# Memory Hub

Preserve concise repository knowledge, not transcripts. SQLite in the current repository's `.memory-hub/` directory is authoritative; Markdown is an export.

## Route the request

Treat the first word after `/memory-hub` as the action. Supported actions:

| Action | Script operation | Read first |
|---|---|---|
| `init` | `init` | [admin.md](references/admin.md) |
| `checkpoint`, `close` | `capture` | [capture.md](references/capture.md), then [capture-schema.md](references/capture-schema.md) |
| `context [task]`, `recall <query> [task]`, `search <query>`, `timeline <id>`, `details <id>...` | matching operation | [retrieval.md](references/retrieval.md) |
| `feedback` | `feedback` | [feedback.md](references/feedback.md) |
| `dream`, `status`, `export [target]`, `server`, `serve`, `stop` | matching operation; `serve` maps to `server` | [admin.md](references/admin.md) |

Read only the references required by the selected action. If no action is supplied, infer it only from an unambiguous request; otherwise list the actions and ask. Do not invent actions.

## Run the script

Use full mode when Python 3.10+, Git, and script execution are available. Resolve `scripts/memory_hub.py` relative to this `SKILL.md`, resolve the repository root, pass it as an absolute `--repo-root`, and quote paths and task text.

```bash
python3 "<skill-directory>/scripts/memory_hub.py" <operation> --repo-root "<repository-root>"
```

Operation-specific arguments:

```text
init:     [--instruction-file AGENTS.md|CLAUDE.md|.github/copilot-instructions.md]...
capture:  --input "<temporary-json>"
context:  [--task "<task>"] [--profile compact|standard|detailed]
recall:   "<query>" [--task "<task>"]
search:   "<query>" [--task "<task>"] [--limit N] [--offset N] [--type <type>] [--json]
timeline: <record-id> [--before N] [--after N] [--json]
details:  <record-id>... [--json]
dream:    [--apply]
feedback: --input "<temporary-json>"
export:   [decisions|session <id>]
```

Use compact context unless the user explicitly needs more detail. Temporary JSON must be outside `.memory-hub/`, contain only the validated object, and be removed after execution. Do not ask the user to run internal commands. If `python3` is unavailable, use `python` only after verifying Python 3.10+.

## Boundaries

The agent handles intent, semantic extraction, uncertainty, and explanations. The script handles repository discovery, Git facts, validation, persistence, retrieval, IDs, timestamps, exports, and server lifecycle.

Do not fabricate Git facts, timestamps, IDs, or persistence. Do not read proprietary agent session databases. Do not store suspected secrets. Current code, tests, and explicit developer instructions outrank retrieved memory.

In reduced mode, state that persistence, verified Git state, retrieval, export, and browser actions are unavailable. For `checkpoint` or `close`, return schema-version-1 JSON and a concise summary without claiming persistence. Other actions require full mode.

On failure, preserve source data, report the operation and actionable error, and do not claim success. Never edit exports to simulate persistence, replace a database, kill an unverified process, or expose the server beyond `127.0.0.1`.
