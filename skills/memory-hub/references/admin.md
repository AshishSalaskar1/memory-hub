# Administrative Workflows

## Init

Run `init`. Describe cold-start claims as observed, inferred, or unknown. If proactive context is not configured, offer only instruction files relevant to the active host and require approval before rerunning `init` with `--instruction-file`. The script updates its marked block idempotently.

## Dream

Run `dream` without `--apply`, show the audit, and request approval before applying. Apply may rebuild search indexes and repair only mechanically provable links or statuses. It must not merge similar records, delete history, invent conclusions, or alter human authority.

## Status And Export

Run the matching operation. SQLite remains authoritative. Forward supported `decisions` or `session <id>` export targets and report generated paths.

## Server Lifecycle

Run `server` or its `serve` alias and report the exact `127.0.0.1` URL. Reuse a healthy server. `stop` may terminate only the process validated by `.memory-hub/server.json`.

The browser exports standalone HTML, a Markdown ZIP, or a portable SQLite snapshot. To migrate a snapshot, place `memory.db` under the target repository's `.memory-hub/` directory and run `init`.
