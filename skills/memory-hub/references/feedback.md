# Feedback Workflow

Ask one concise question at a time:

1. Type: `positive`, `correction`, `concern`, or `suggestion`.
2. Scope: `repository`, `session`, or `record`.
3. Target ID for session or record scope. Use focused lookup; never guess.
4. Feedback body.
5. Sentiment: `positive`, `neutral`, or `negative`.
6. Optional rating from 1 through 5.

Summarize the result and offer `save`, `edit`, or `cancel`. On save, write the standalone feedback object from [capture-schema.md](capture-schema.md) to a temporary file, run `feedback --input`, remove the file, and report its stable ID.

Feedback influences retrieval but never silently rewrites or supersedes its target. In reduced mode, return the JSON and state that it was not persisted.
