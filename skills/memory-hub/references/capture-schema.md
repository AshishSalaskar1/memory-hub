# Capture Schema Version 1

The active agent sends one JSON object to `capture`. It contains extracted knowledge, not a raw transcript. Unknown optional values should be omitted rather than guessed. All timestamps, generated IDs, and objective Git metadata may be added or verified by the script.

## Top-level contract

```json
{
  "schema_version": 1,
  "session": {
    "mode": "checkpoint",
    "agent": "github-copilot",
    "model": "github-copilot/gpt-5.6-sol",
    "goal": "Implement the capture contract",
    "outcome": "partial",
    "summary": "Defined the versioned session capture payload."
  },
  "checkpoints": [],
  "tasks": [],
  "changes": [],
  "decisions": [],
  "directions": [],
  "capabilities": [],
  "open_loops": [],
  "evidence": [],
  "relationships": []
}
```

Required top-level fields are `schema_version`, `session`, and all nine entity arrays shown above. `schema_version` must be integer `1`. Unknown top-level fields are invalid. Strings must be trimmed and non-empty unless noted; IDs are capture-local strings used by relationships and may be omitted when no cross-reference is needed.

## Common memory fields

Entity objects may include:

| Field | Values / meaning |
|---|---|
| `id` | Capture-local unique identifier, such as `decision-1` |
| `scope` | Concise repository, component, feature, or file scope |
| `source` | `observed`, `agent`, `human`, `hypothesis`, or `future-intent` |
| `confidence` | `high`, `medium`, or `low` |
| `confirmation` | `human-confirmed`, `explicit-human`, `agent-inferred`, `unconfirmed`, or `not-required` |
| `status` | Entity-specific status below |
| `evidence_ids` | Array of IDs from `evidence` |
| `supersedes` | ID of an older record this record replaces |

`source` says where a claim came from; `confidence` says how certain it is; `confirmation` says whether a human approved it. These are independent. Use `source: human` plus `confirmation: explicit-human` for a direct instruction in the active conversation. Use `human-confirmed` only after confirmation. Observed tool facts normally use `not-required`.

## Session

`session.mode` is required and must be `checkpoint` or `close`. The script associates repeated checkpoints with the current logical session; `close` finalizes it. If no logical session is active, either mode creates one, and `close` immediately finalizes it. Other fields:

| Field | Required | Values / meaning |
|---|---:|---|
| `agent` | no | Agent/product identifier when available |
| `model` | no | Model identifier when available |
| `goal` | yes | Logical session objective |
| `outcome` | yes | `completed`, `partial`, `blocked`, `abandoned`, or `unknown` |
| `summary` | yes | Concise result so far |

## Entities

### `checkpoints`

Normally one object for `checkpoint` mode and empty for `close`; the script may create the persisted checkpoint record. Fields: optional `id`, required `summary`, optional `open_context`, and optional common fields. `open_context` is concise context needed to continue, not a transcript.

### `tasks`

Required: `title`, `status`, `summary`. Status: `planned`, `in-progress`, `completed`, `blocked`, `deferred`, or `abandoned`. Optional: `result`, `tests` (string array), `file_paths` (repository-relative string array), and common fields.

### `changes`

Required: `path`, `kind`, `summary`. `path` is repository-relative. Kind: `added`, `modified`, `deleted`, `renamed`, or `untracked`. Optional: `old_path`, `task_ids`, and common fields. A change is an objective file-level fact; semantic claims belong in other entities. The script should verify against Git when possible.

### `decisions`

Required: `title`, `status`, `scope`, `rationale`. Status: `proposed`, `active`, `rejected`, `superseded`, or `needs-review`. `rationale` is a non-empty string array. Optional: `alternatives`, `tradeoffs`, `reconsider_when` (all string arrays), and common fields. A brainstorming option is not an active decision.

### `directions`

Required: `instruction`, `status`, `scope`, `origin`, `importance`. Status: `active` or `superseded`. Origin: `human` or `agent`. Importance: `high`, `medium`, or `low`. Optional: `correction_of` and common fields. Do not set `origin: human` for an agent-created recommendation.

### `capabilities`

Required: `name`, `status`, `summary`. Status: `planned`, `partial`, `implemented`, or `deprecated`. Optional: `file_paths`, `test_paths`, `limitations` (string arrays), and common fields. `implemented` requires code or test evidence; intent alone is `planned`.

### `open_loops`

Required: `title`, `kind`, `status`, `summary`. Kind: `unfinished-work`, `blocker`, `question`, `deferred-refactor`, `missing-test`, or `workaround`. Status: `open`, `blocked`, `deferred`, or `resolved`. Optional: `next_step`, `owner`, and common fields.

### `evidence`

Required: `id`, `kind`, `summary`. Kind: `git`, `file`, `test`, `tool-output`, `human-statement`, or `agent-context`. Optional: `reference` (commit, command, path, or concise locator) and `observed_at`. Evidence must summarize relevant proof, not embed secrets or large source excerpts.

### `relationships`

Required: `from_id`, `type`, `to_id`. Both IDs must identify entities in the payload or stable stored IDs accepted by the implementation. Type: `supports`, `implements`, `affects`, `depends-on`, `blocks`, `resolves`, `supersedes`, `evidenced-by`, `belongs-to`, or `related-to`. Optional: `summary`.

The repository entity is managed by `init` and Git inspection; it is not duplicated in capture input. The session is the envelope object. Checkpoint is represented by `session.mode` and optionally described in `checkpoints`. Thus all planned entities are represented without trusting the agent for database identity or repository facts.

## Complete example

```json
{
  "schema_version": 1,
  "session": {
    "mode": "close",
    "agent": "opencode",
    "model": "example/model",
    "goal": "Choose repository memory storage",
    "outcome": "completed",
    "summary": "Selected SQLite and documented an export boundary."
  },
  "checkpoints": [],
  "tasks": [
    {
      "id": "task-1",
      "title": "Define storage strategy",
      "status": "completed",
      "summary": "Compared structured local storage options.",
      "source": "agent",
      "confidence": "high",
      "confirmation": "not-required",
      "evidence_ids": ["evidence-1"]
    }
  ],
  "changes": [
    {
      "id": "change-1",
      "path": "SKILL.md",
      "kind": "added",
      "summary": "Added the skill contract.",
      "source": "observed",
      "confidence": "high",
      "confirmation": "not-required",
      "evidence_ids": ["evidence-1"]
    }
  ],
  "decisions": [
    {
      "id": "decision-1",
      "title": "Use SQLite as canonical storage",
      "status": "active",
      "scope": "repository memory",
      "rationale": ["Supports structured queries", "Supports migrations and relationships"],
      "alternatives": ["Canonical Markdown files"],
      "source": "human",
      "confidence": "high",
      "confirmation": "explicit-human"
    }
  ],
  "directions": [
    {
      "id": "direction-1",
      "instruction": "Do not read proprietary agent session databases.",
      "status": "active",
      "scope": "capture",
      "origin": "human",
      "importance": "high",
      "source": "human",
      "confidence": "high",
      "confirmation": "explicit-human"
    }
  ],
  "capabilities": [
    {
      "id": "capability-1",
      "name": "Structured session capture",
      "status": "planned",
      "summary": "Validate and persist versioned captures.",
      "limitations": ["Implementation is pending"],
      "source": "future-intent",
      "confidence": "high",
      "confirmation": "not-required"
    }
  ],
  "open_loops": [
    {
      "id": "loop-1",
      "title": "Implement capture persistence",
      "kind": "unfinished-work",
      "status": "open",
      "summary": "Add schema validation and SQLite writes.",
      "next_step": "Implement scripts/memory_hub.py capture.",
      "source": "future-intent",
      "confidence": "high",
      "confirmation": "not-required"
    }
  ],
  "evidence": [
    {
      "id": "evidence-1",
      "kind": "git",
      "summary": "Git reports SKILL.md as added.",
      "reference": "git status --short"
    }
  ],
  "relationships": [
    {"from_id": "change-1", "type": "implements", "to_id": "task-1"},
    {"from_id": "task-1", "type": "evidenced-by", "to_id": "evidence-1"}
  ]
}
```

## Validation and safety

Reject unsupported schema versions, missing required fields or arrays, invalid enum values, duplicate IDs, dangling relationships/evidence references, and absolute or escaping file paths. Return a field path and actionable reason, for example: `decisions[0].status: expected proposed|active|rejected|superseded|needs-review`.

Redact credentials, tokens, private keys, and secret values before validation. Never silently downgrade malformed or uncertain content, and never convert agent inference into human-confirmed memory.

## Standalone feedback contract

Feedback is stored through the `feedback` operation and is not a new required array in capture schema version 1. This keeps existing capture payloads compatible.

```json
{
  "type": "correction",
  "scope": "record",
  "record_id": "dec_0123456789abcdef",
  "body": "The rationale should also mention the offline requirement.",
  "sentiment": "negative",
  "rating": 2
}
```

Required fields:

- `type`: `positive`, `correction`, `concern`, or `suggestion`
- `scope`: `repository`, `session`, or `record`
- `body`: trimmed, non-empty feedback text
- `sentiment`: `positive`, `neutral`, or `negative`

Optional field:

- `rating`: integer from `1` through `5`; omit it when the user does not want to provide a rating

Scope rules:

- Repository feedback has no `session_id` or `record_id`.
- Session feedback requires a stable `session_id` and has no `record_id`.
- Record feedback requires a stable `record_id`. Its owning session is derived automatically; an optional matching `session_id` may be supplied.
- A record target must be a task, change, decision, direction, capability, open loop, checkpoint, or evidence record in the current repository.

Unknown fields, invalid enums, invalid ratings, missing targets, cross-session targets, and suspected secrets are rejected before persistence. Feedback does not automatically update, supersede, or delete the memory it references.
