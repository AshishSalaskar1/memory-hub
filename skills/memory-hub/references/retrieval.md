# Retrieval Workflow

## Context

Use `context --task "<task>" --profile compact` once when work depends on repository history, architecture, conventions, prior decisions, or unresolved work. Skip it for isolated fixes, trivial requests, and unrelated work.

Profiles:

| Profile | Character budget | Global record limit |
|---|---:|---:|
| `compact` | 5,000 | 12 |
| `standard` | 8,000 | 20 |
| `detailed` | 12,000 | 35 |

Use `standard` or `detailed` only when explicitly useful. The script ranks records globally, prioritizes relevance and human authority, removes close duplicates, excludes superseded records, and emits only complete records within the budget.

## Recall

Use `recall "<specific question>" --task "<current task>"` at a decision point instead of loading broad context again. Return only the best matches with stable ID, type, status, and concise detail. The default is five results; lower it for narrow questions.

Treat retrieved memory as supporting evidence. Verify implementation claims against current code and tests.

## Progressive retrieval

Use the three-layer workflow when relevance is uncertain, the memory store is broad, or loading complete records immediately would add unnecessary context:

1. Run `search "<query>" --task "<current task>" --limit 5` to inspect a compact index. Review IDs, types, titles, status, authority, dates, and estimated detail cost.
2. Run `timeline <record-id> --before 3 --after 3` only when chronology or surrounding work matters. It returns a compact window from the anchor record's session.
3. Run one batched `details <record-id>...` request for only the records that need full inspection.

Stop after any layer that supplies enough evidence. Increase the search limit or timeline depth only when needed. Do not fetch details for every search result by default.

Use `context` and `recall` as the shorter paths when their intent is already clear:

| Need | Retrieval path |
|---|---|
| Broad orientation for a known substantial task | `context` |
| One focused historical question | `recall` |
| Survey memories before deciding what matters | `search` |
| Understand events around a selected memory | `search` then `timeline` |
| Inspect exact rationale, evidence, or fields | `search` then batched `details` |

`search` supports `--limit`, `--offset`, `--type`, and `--json`. Search output is intentionally compact and does not include full rationale or body fields. `details` preserves requested ID order and returns complete records. Verify implementation claims against current code and tests after retrieval.
