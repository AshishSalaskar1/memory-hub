# Capture Schema Version 1

Send extracted knowledge, never a transcript. The script supplies timestamps, stable IDs, Git metadata, omitted empty arrays, and routine provenance defaults.

## Minimal Payload

```json
{
  "schema_version": 1,
  "session": {
    "mode": "checkpoint",
    "goal": "Implement compact retrieval",
    "outcome": "partial",
    "summary": "Added bounded context profiles."
  },
  "tasks": [
    {
      "title": "Implement compact retrieval",
      "status": "in-progress",
      "summary": "Added global ranking and output budgets."
    }
  ]
}
```

Only `schema_version` and `session` are required at the top level. Omitted entity arrays become empty. Unknown fields are rejected. `schema_version` must be integer `1`; strings must be trimmed and non-empty.

## Session

Required fields:

| Field | Values |
|---|---|
| `mode` | `checkpoint`, `close` |
| `goal` | Logical session objective |
| `outcome` | `completed`, `partial`, `blocked`, `abandoned`, `unknown` |
| `summary` | Concise result so far |

Optional: `agent`, `model`.

## Entity Arrays

| Array | Required fields | Optional content |
|---|---|---|
| `checkpoints` | `summary` | `open_context` |
| `tasks` | `title`, `status`, `summary` | `result`, `tests`, `file_paths` |
| `changes` | `path`, `kind`, `summary` | `old_path`, `task_ids` |
| `decisions` | `title`, `status`, `scope`, `rationale` | `alternatives`, `tradeoffs`, `reconsider_when` |
| `directions` | `instruction`, `status`, `scope`, `origin`, `importance` | `correction_of` |
| `capabilities` | `name`, `status`, `summary` | `file_paths`, `test_paths`, `limitations` |
| `open_loops` | `title`, `kind`, `status`, `summary` | `next_step`, `owner` |
| `evidence` | `id`, `kind`, `summary` | `reference`, `observed_at` |
| `relationships` | `from_id`, `type`, `to_id` | `summary` |

Omit `changes` when ordinary Git working-tree records are sufficient. The script derives their paths, kinds, and observed provenance. Include `changes` when semantic summaries or task links add value; an explicit empty array means store no change records.

## Status Values

| Entity | Values |
|---|---|
| Task | `planned`, `in-progress`, `completed`, `blocked`, `deferred`, `abandoned` |
| Change kind | `added`, `modified`, `deleted`, `renamed`, `untracked` |
| Decision | `proposed`, `active`, `rejected`, `superseded`, `needs-review` |
| Direction | `active`, `superseded`; origin `human` or `agent`; importance `high`, `medium`, or `low` |
| Capability | `planned`, `partial`, `implemented`, `deprecated` |
| Open loop | kind `unfinished-work`, `blocker`, `question`, `deferred-refactor`, `missing-test`, or `workaround`; status `open`, `blocked`, `deferred`, or `resolved` |
| Evidence kind | `git`, `file`, `test`, `tool-output`, `human-statement`, `agent-context` |
| Relationship | `supports`, `implements`, `affects`, `depends-on`, `blocks`, `resolves`, `supersedes`, `evidenced-by`, `belongs-to`, `related-to` |

Decision `rationale` is a non-empty string array. An `implemented` capability requires a file, test, or evidence reference.

## Common Optional Fields

`id`, `scope`, `source`, `confidence`, `confirmation`, `status`, `evidence_ids`, and `supersedes` are available where applicable. Capture-local IDs are needed only for relationships within the payload.

Defaults when omitted:

| Record | `source` | `confidence` | `confirmation` |
|---|---|---|---|
| Change or tool-backed evidence | `observed` | `high` | `not-required` |
| Human direction | `human` | `high` | `explicit-human` |
| Other semantic record | `agent` | `medium` | `agent-inferred` |

Override defaults only when needed. Allowed source values are `observed`, `agent`, `human`, `hypothesis`, and `future-intent`; confidence is `high`, `medium`, or `low`; confirmation is `human-confirmed`, `explicit-human`, `agent-inferred`, `unconfirmed`, or `not-required`. Human confirmation requires `source: human`.

Use repository-relative paths. Omit unknown optional values rather than guessing. Stable stored IDs may be used by `supersedes`, evidence links, task links, corrections, and relationships.

## Feedback Payload

Feedback uses a separate operation and payload:

```json
{
  "type": "correction",
  "scope": "record",
  "record_id": "dec_0123456789abcdef",
  "body": "Also account for the offline requirement.",
  "sentiment": "negative",
  "rating": 2
}
```

Required: `type` (`positive`, `correction`, `concern`, `suggestion`), `scope` (`repository`, `session`, `record`), `body`, and `sentiment` (`positive`, `neutral`, `negative`). Rating is optional from 1 through 5. Session scope requires `session_id`; record scope requires `record_id`; repository scope accepts neither.

## Safety

The script rejects invalid enums, unknown fields, duplicate IDs, dangling references, unsafe paths, and suspected secrets. Do not silently discard invalid data or convert inference into human-confirmed memory.
