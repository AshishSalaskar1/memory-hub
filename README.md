# Memory Hub

Memory Hub is a local-first Agent Skill that turns useful coding-session context into durable repository knowledge.

> Git remembers what changed. Memory Hub remembers why.

The skill is designed for installation through [skills.sh](https://skills.sh). It does not install a global CLI and does not read proprietary agent session databases. The active agent summarizes context it still has; a bundled Python script performs deterministic storage and retrieval.

## Requirements

- Python 3.10 or newer
- Git, for repository metadata and change verification
- An agent that supports the open [Agent Skills](https://agentskills.io) format
- Permission for the agent to run the bundled Python script for full mode

Without Python, Git, or shell access, the skill can still produce a structured summary in reduced mode, but it cannot persist or retrieve SQLite memory.

## Installation

### Recommended: skills.sh

Once this repository is published, install it with the skills CLI from the repository that contains `SKILL.md`:

```bash
npx skills@latest add <OWNER>/memory-hub-skill
```

The installer finds `skills/memory-hub/SKILL.md`, then lets you choose the skill, supported agents, and installation scope. Run it from a project directory for a project-local installation.

Review third-party skills before allowing them to execute shell commands. Memory Hub needs shell access in full mode because it invokes its bundled Python script and Git.

### GitHub Copilot in VS Code, JetBrains, or GitHub

GitHub Copilot recognizes project skills in any of these directories:

```text
.github/skills/memory-hub/
.agents/skills/memory-hub/
.claude/skills/memory-hub/
```

Install the complete repository directory, not only `SKILL.md`, because the skill also needs `scripts/`, `references/`, and `assets/`. For example:

```text
your-project/
`-- .github/
    `-- skills/
        `-- memory-hub/
            |-- SKILL.md
            |-- scripts/
            |-- references/
            `-- assets/
```

For a personal installation shared across projects, place the same directory at `~/.copilot/skills/memory-hub/` or `~/.agents/skills/memory-hub/`.

GitHub CLI 2.90.0 or newer can also install a published skill for Copilot:

```bash
gh skill preview <OWNER>/memory-hub-skill memory-hub
gh skill install <OWNER>/memory-hub-skill memory-hub
```

### GitHub Copilot CLI

Copilot CLI uses the same personal skill directories as other GitHub Copilot surfaces:

```text
~/.copilot/skills/memory-hub/
~/.agents/skills/memory-hub/
```

Use `gh skill install` as shown above, or install through `npx skills@latest add`. Start a new Copilot CLI session after installing so the skill is discovered.

### OpenCode

OpenCode discovers project-local skills from:

```text
.opencode/skills/memory-hub/
.agents/skills/memory-hub/
.claude/skills/memory-hub/
```

For a global installation, use:

```text
~/.config/opencode/skills/memory-hub/
~/.agents/skills/memory-hub/
~/.claude/skills/memory-hub/
```

Install through `npx skills@latest add` or place the complete skill directory in one of those locations. Quit and restart OpenCode after installation because skill configuration is loaded at startup.

If your OpenCode permission configuration restricts skills or shell commands, allow `memory-hub` and approve the Python and Git operations when prompted.

### Claude Code

Install the complete skill directory for one project at:

```text
.claude/skills/memory-hub/
```

For all projects, use:

```text
~/.claude/skills/memory-hub/
```

You can use `npx skills@latest add` and select Claude Code, or copy `skills/memory-hub/` into the appropriate directory.

### Codex and other compatible agents

Many Agent Skills-compatible tools recognize the shared directory convention:

```text
.agents/skills/memory-hub/
~/.agents/skills/memory-hub/
```

Use the project path to keep the skill scoped to one repository, or the home-directory path to make it available across projects. The `skills.sh` installer can configure supported hosts such as Codex, Cursor, Windsurf, Gemini CLI, and others; run `npx skills@latest add <OWNER>/memory-hub-skill` and select the desired agent.

Whichever location you use, the resulting directory must retain this structure:

```text
memory-hub/
|-- SKILL.md
|-- scripts/memory_hub.py
|-- references/
`-- assets/web/
```

Replace `<OWNER>` with the GitHub owner or organization after this repository is published.

### Repository layout

Following the structure used by [mattpocock/skills](https://github.com/mattpocock/skills), repository-level documentation and tests stay at the root while every installable skill is self-contained under `skills/`:

```text
memory-hub-skill/
|-- README.md
|-- LICENSE
|-- tests/
`-- skills/
    `-- memory-hub/
        |-- SKILL.md
        |-- scripts/
        |-- references/
        `-- assets/web/
```

This allows installers to copy `skills/memory-hub/` without including repository development files.

## Usage

Open the target repository in your agent, then invoke Memory Hub. The public interface is the skill, not the internal Python script.

Initialize once per repository:

```text
/memory-hub init
```

Retrieve relevant memory before starting work:

```text
/memory-hub context implement Markdown export
```

Ask a focused question while working without loading every memory:

```text
/memory-hub recall why did we choose SQLite?
```

Record feedback about the repository or an earlier memory:

```text
/memory-hub feedback
```

Save progress during a long session and finalize it at the end:

```text
/memory-hub checkpoint
/memory-hub close
```

Inspect or share stored knowledge:

```text
/memory-hub status
/memory-hub dream
/memory-hub export
/memory-hub server
/memory-hub stop
```

If an agent does not support arguments after a slash invocation, invoke the skill and put the request on the next line:

```text
/memory-hub
Retrieve context for implementing Markdown export.
```

Agents may also discover the skill from a natural-language request. Examples include `Initialize Memory Hub for this repository`, `Checkpoint this session`, or `Start the local Memory Hub server`.

## Actions

### `/memory-hub init`

Initializes Memory Hub for the repository currently open in the agent.

```text
/memory-hub init
```

It:

- Finds the repository root
- Creates the local `.memory-hub/` directory
- Creates or migrates `.memory-hub/memory.db`
- Writes `.memory-hub/config.json`
- Records the current Git branch, commit, dirty state, and changed files when Git is available
- Creates `.memory-hub/exports/` for future Markdown exports

Run this once when adding Memory Hub to a repository. It is safe to run again; initialization and migrations are idempotent. It does not reconstruct old discussions or historical rationale from Git.

### `/memory-hub checkpoint`

Saves the useful state of the current coding session without ending it.

```text
/memory-hub checkpoint
```

The active agent reviews the conversation and current repository state, then extracts structured memories such as:

- Work completed so far
- Tasks still in progress
- Decisions and their rationale
- Developer instructions and corrections
- Files changed and available Git evidence
- Capability changes
- Blockers, questions, and next steps

The script validates the capture and stores it in SQLite. Repeated checkpoints remain attached to the same active logical session. Use checkpoints during long tasks, before context compaction, or whenever losing the current conversation would be costly.

Memory Hub stores a structured summary, not the raw conversation. The agent may ask you to confirm consequential or uncertain interpretations before saving them.

### `/memory-hub close`

Captures the final state of the current work and closes the logical session.

```text
/memory-hub close
```

It performs the same extraction and validation as `checkpoint`, but records the session as closed. The final capture should distinguish completed work from incomplete, blocked, deferred, or abandoned work so a future agent can resume accurately.

If there is an active checkpointed session, `close` finalizes it. If there is no active session, Memory Hub creates a session from the currently available context and immediately closes it. Closing does not delete or compact earlier checkpoints.

### `/memory-hub context [task]`

Retrieves a concise context pack for the next piece of work.

```text
/memory-hub context
/memory-hub context implement Markdown export
```

Without a task, it returns a short overview of recent repository state. With a task, it ranks stored records by relevance and prioritizes:

- Active decisions
- Human-confirmed developer directions
- Relevant capabilities and files
- Open work and blockers
- In-progress or planned tasks

The result is intentionally bounded rather than a dump of every session. Use it at the beginning of a session or before changing an unfamiliar part of the repository.

### `/memory-hub recall <query>`

Searches for a small, ranked set of memories related to a specific question.

```text
/memory-hub recall why did we choose SQLite?
/memory-hub recall authentication constraints for the OAuth task
```

The skill passes both the question and the current task to the local search operation when that context is available. Ranking considers:

- Words from the specific question
- Overlap with the current task
- Exact title matches
- Active versus superseded status
- Human-confirmed authority
- Recency as a final tie-breaker

Only the highest-ranked matches are returned, with their stable IDs and memory types. Superseded memories are excluded from normal retrieval. This is the preferred command when the agent reaches a specific decision point during implementation.

### How agents use memory

Memory Hub uses progressive, on-demand retrieval instead of placing the full database into every prompt:

1. At the start of substantial work, the agent runs `context <current task>` to get a compact orientation pack.
2. The agent works from the repository normally rather than treating memory as a replacement for current code.
3. When a specific historical question arises, the agent runs `recall <question>` with the current task as additional ranking context.
4. The agent gives greater weight to active, human-confirmed directions and decisions.
5. The agent retrieves another small set only if the task reaches a different concern.

For example, while implementing login the agent might retrieve broad context once, then ask focused questions later:

```text
/memory-hub context implement OAuth login
/memory-hub recall what authentication constraints did the developer specify?
/memory-hub recall why are refresh tokens stored server-side?
```

This keeps unrelated sessions out of the context window while still making repository history available at the point where it matters.

### `/memory-hub dream`

Audits and mechanically consolidates the memory store without asking a model to rewrite history.

```text
/memory-hub dream
```

The default command is a dry run. It reports:

- Search-index records that can be rebuilt
- Missing reciprocal supersession links that can be repaired safely
- Decision or direction statuses that conflict with known supersession links
- Dangling references
- Exact duplicate candidates that may need human review

After showing the report and receiving approval, the agent can apply safe repairs:

```text
/memory-hub dream apply
```

Applied dreaming rebuilds the full-text index and repairs only relationships that are mechanically certain. It does not merge similar records, delete history, invent rationale, reinterpret memories, or change human confirmation. Ambiguous duplicates remain visible for manual review.

### `/memory-hub feedback`

Starts a short, conversational feedback flow.

```text
/memory-hub feedback
```

The agent asks one question at a time rather than presenting a large form. It collects:

- Feedback type: positive, correction, concern, or suggestion
- Scope: the whole repository, a session, or a specific memory record
- The target session or record when required
- Your feedback in your own words
- Sentiment: positive, neutral, or negative
- An optional rating from 1 to 5

Before saving, the agent shows a concise summary and lets you save, edit, or cancel. Feedback receives its own stable ID and becomes available to context retrieval, focused recall, exports, session details, and the timeline.

Feedback does not silently alter the memory it references. A correction remains an explicit human signal that future agents can see and weigh during relevant work.

Example interaction:

```text
You: /memory-hub feedback
Agent: What kind of feedback is this: positive, correction, concern, or suggestion?
You: Correction
Agent: Does it apply to the repository, a session, or a specific memory record?
You: A specific decision
Agent: Which decision should it reference?
You: dec_0123456789abcdef
Agent: What should be corrected?
You: The rationale should include the offline requirement.
Agent: Is the sentiment positive, neutral, or negative?
You: Neutral
Agent: Add an optional rating from 1 to 5, or skip it?
You: Skip
Agent: Save this correction? [save/edit/cancel]
```

The same feature is available in the local browser under **Feedback**. Select **Add feedback**, choose its scope, complete the fields, and submit it. Existing feedback can be opened, edited, and deleted like other memory records.

### `/memory-hub status`

Shows a quick health and activity summary for the repository memory store.

```text
/memory-hub status
```

The report includes:

- Repository name and database path
- Total captured sessions
- Last capture time
- Current active session, if any
- Number of active decisions
- Number of open work items
- Number of feedback entries
- Number of unconfirmed or agent-inferred memories

Use this to confirm that Memory Hub is initialized and captures are being persisted.

### `/memory-hub export [target]`

Generates human-readable Markdown from the SQLite database. SQLite remains authoritative; editing generated files does not update stored memory.

```text
/memory-hub export
/memory-hub export decisions
/memory-hub export session <SESSION_ID>
```

The default export writes a browsable set under `.memory-hub/exports/`, including repository state, decisions, developer directions, capabilities, open work, feedback, and session summaries.

`export decisions` refreshes only `decisions.md`. `export session <SESSION_ID>` exports one session, including its tasks, checkpoints, changes, decisions, directions, capabilities, open loops, evidence, and relationships. Session IDs such as `ses_ab12cd34...` appear in capture output and status/context records.

Use exports for human review, archival, or optional Git tracking. Do not use exported Markdown as an input database.

### `/memory-hub server`

Starts the local browser interface for exploring repository memory.

```text
/memory-hub server
```

It:

- Binds only to `127.0.0.1`
- Selects an available local port
- Starts in the background and returns control promptly
- Records its PID, port, and instance identity in `.memory-hub/server.json`
- Reuses the existing server when it is already healthy
- Prints a URL such as `http://127.0.0.1:47321`

The browser provides overview, timeline, decisions, capabilities, developer directions, open-work, filtering, and search views. It has no telemetry or cloud synchronization. `serve` is accepted as an alias for `server`.

Sessions in the overview and timeline are interactive. Select one to open its complete ledger, including checkpoints, tasks, changes, decisions, directions, capabilities, open loops, evidence, and relationships. Session metadata is read-only because its timestamps, Git snapshot, and lifecycle are maintained by Memory Hub.

Individual memory records can be opened from their main view, a session ledger, or search results. The detail panel allows supported semantic fields to be edited and unreferenced records to be permanently deleted. Identity, timestamps, Git evidence, and session ownership cannot be edited. Deletion is blocked when another memory still references the record so history cannot be silently corrupted.

### `/memory-hub stop`

Stops the local browser server associated with the current repository.

```text
/memory-hub stop
```

Memory Hub verifies the token and process ID in `.memory-hub/server.json` before requesting shutdown. It does not search for or kill arbitrary Python processes. Running `stop` when no server is active is safe.

### Typical workflow

```text
# Once per repository
/memory-hub init

# At the beginning of work
/memory-hub context add OAuth login

# When a focused historical question arises
/memory-hub recall why are refresh tokens stored server-side?

# During a long session
/memory-hub checkpoint

# Record a correction or suggestion
/memory-hub feedback

# When the work session ends
/memory-hub close

# Periodically audit and consolidate the store
/memory-hub dream

# Inspect or share the accumulated memory
/memory-hub status
/memory-hub export
/memory-hub server
```

## Storage model

In full mode, Memory Hub stores repository-local data under:

```text
.memory-hub/
|-- memory.db
|-- config.json
|-- exports/
`-- server.json
```

SQLite is authoritative. Markdown is generated on demand and editing exports does not modify the database. The optional browser is local-only and binds to `127.0.0.1`.

Full mode requires Python 3.10+, Git, and permission for the agent to run scripts. Reduced mode can prepare structured capture JSON and Markdown summaries, but cannot persist, verify Git state, retrieve SQLite context, export from the database, or manage the browser.

## Capture contract

`checkpoint` preserves progress in an open logical session. `close` finalizes it. Both use schema version 1 with `session.mode` set to `checkpoint` or `close`, and can capture tasks, changes, decisions, directions, capabilities, open loops, evidence, and relationships. Provenance and confirmation fields keep agent interpretations distinct from observed and human-confirmed facts.

Feedback uses a separate payload so capture schema version 1 remains compatible. It can reference the repository, a session, or a specific memory record without mutating that target.

See:

- [SKILL.md](skills/memory-hub/SKILL.md) for the executable agent contract
- [Capture schema](skills/memory-hub/references/capture-schema.md) for version 1 JSON
- [Memory types](skills/memory-hub/references/memory-types.md) for semantics and authority
- [Workflows](skills/memory-hub/references/workflows.md) for action and failure behavior

## Development

The runtime and tests use only the Python standard library:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/memory-hub/scripts/memory_hub.py
node --check skills/memory-hub/assets/web/app.js
```

## Privacy

Memory Hub is local-first, has no required cloud account or telemetry, and stores extracted knowledge rather than raw transcripts. Captures should redact secrets before persistence. Context already lost by an agent cannot be reconstructed unless it was previously checkpointed.

## License

[MIT](LICENSE)
