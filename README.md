# Memory Hub

Your coding agent starts each new session with a clean slate. The code is still there, but the reasoning behind it often is not.

**Memory Hub gives your repository a memory.** It saves the useful parts of a coding session, such as decisions, constraints, unfinished work, and developer feedback, then brings back only what matters for the next task.

> Git remembers what changed. Memory Hub remembers why.

Everything stays in the repository. There is no account to create, no cloud service to connect, and no raw transcript archive to manage.

## What it feels like

Imagine returning to a project after a few weeks and asking:

```text
/memory-hub recall why did we choose SQLite?
```

Instead of searching through old chats, your agent can retrieve the decision, its rationale, and the work it affected.

Memory Hub can help your agent remember:

- Why an architectural choice was made
- What you asked it to do differently next time
- Which work is complete, blocked, or still in progress
- Where a capability lives in the codebase
- What changed during a long session

It stores structured summaries rather than full conversations. The repository remains the source of truth for code; Memory Hub supplies the missing context around it.

## Try it in five minutes

### 1. Install the skill

From your project directory:

```bash
npx skills@latest add <OWNER>/memory-hub-skill
```

Select `memory-hub`, your coding agent, and a project-local installation when prompted. Replace `<OWNER>` with the GitHub owner or organization once this repository is published.

### 2. Initialize repository memory

Open the project in your agent and run:

```text
/memory-hub init
```

This creates a local `.memory-hub/` directory for the repository.

### 3. Save useful progress

During a long session:

```text
/memory-hub checkpoint
```

When the session is finished:

```text
/memory-hub close
```

The agent extracts decisions, directions, changes, open questions, and next steps from the context it still has. You can review consequential or uncertain interpretations before they are stored.

### 4. Pick up where you left off

At the start of a later session:

```text
/memory-hub context add OAuth login
```

When a specific question comes up:

```text
/memory-hub recall why are refresh tokens stored server-side?
```

That is the core loop: **initialize once, capture as you work, retrieve when needed.**

## A typical day with Memory Hub

```text
# Begin with the context that matters for today's task
/memory-hub context add OAuth login

# Save progress before the conversation gets long
/memory-hub checkpoint

# Ask about one earlier decision
/memory-hub recall what authentication constraints did the developer specify?

# Record a correction or suggestion
/memory-hub feedback

# Finish the session
/memory-hub close
```

You can use natural language too. Requests such as `Initialize Memory Hub for this repository`, `Checkpoint this session`, and `Start the local Memory Hub server` allow compatible agents to discover and invoke the skill.

## What you can do

| Command | Use it when you want to... |
|---|---|
| `/memory-hub init` | Set up memory for a repository |
| `/memory-hub context [task]` | Get oriented before starting a task |
| `/memory-hub recall <question>` | Find a specific decision, constraint, or piece of history |
| `/memory-hub checkpoint` | Save progress without ending the current session |
| `/memory-hub close` | Save the final state and close the session |
| `/memory-hub feedback` | Record a correction, concern, suggestion, or positive note |
| `/memory-hub status` | Check memory health and recent activity |
| `/memory-hub dream` | Audit the store and preview safe repairs |
| `/memory-hub export` | Generate readable Markdown exports |
| `/memory-hub server` | Browse repository memory in a local web interface |
| `/memory-hub stop` | Stop the local web interface |

If your agent does not accept arguments after a slash command, put the request on the next line:

```text
/memory-hub
Retrieve context for implementing Markdown export.
```

## How it works

Memory Hub splits the work between your coding agent and a small local script:

1. The agent reads the conversation and extracts useful knowledge while it is still available.
2. The bundled Python script validates that capture and stores it in repository-local SQLite.
3. Later, task-aware search returns a small, ranked context pack instead of dumping every past session into the prompt.
4. Git supplies verifiable repository facts such as the current branch, commit, dirty state, and changed files.

This separation matters. The agent handles meaning; deterministic code handles storage, retrieval, IDs, timestamps, and data integrity.

Memory Hub does not inspect proprietary agent session databases and cannot recover a conversation after its context has already been lost. Run `checkpoint` before that happens.

## Explore your memory

Start the local browser:

```text
/memory-hub server
```

Memory Hub returns a URL such as `http://127.0.0.1:47321`. The browser includes an overview, timeline, search, decisions, capabilities, developer directions, feedback, and open work.

Sessions open into a complete ledger of their checkpoints, tasks, changes, decisions, directions, capabilities, open loops, evidence, and relationships. Supported memory fields can be edited, and unreferenced records can be deleted.

The server binds only to `127.0.0.1`. It has no telemetry and does not synchronize data to the cloud. Stop it with:

```text
/memory-hub stop
```

## Command details

### Capture work with `checkpoint` and `close`

Both commands can capture:

- Completed and in-progress tasks
- Decisions and rationale
- Developer instructions and corrections
- Changed files and available Git evidence
- New or changed capabilities
- Blockers, questions, and next steps

`checkpoint` keeps the logical session open, so later captures remain connected to it. `close` records the final state and closes the session. Earlier checkpoints are retained.

The agent distinguishes observed facts, your explicit statements, and its own interpretations. It should ask before persisting a consequential claim when your intent is unclear.

### Retrieve context with `context` and `recall`

Use `context` once near the beginning of substantial work:

```text
/memory-hub context
/memory-hub context implement Markdown export
```

It prioritizes active decisions, human-confirmed directions, relevant capabilities and files, open work, and blockers. Results are deliberately bounded.

Use `recall` for focused questions during implementation:

```text
/memory-hub recall why did we choose SQLite?
/memory-hub recall authentication constraints for the OAuth task
```

Search ranking considers the question, the current task, title matches, status, human confirmation, and recency. Superseded memories are excluded from normal retrieval.

### Record human feedback

Run:

```text
/memory-hub feedback
```

The agent asks one question at a time about the feedback type, scope, target, sentiment, and optional rating. You review a short summary before saving it.

Feedback can apply to the repository, a session, or a specific memory record. It remains an explicit human signal; it does not silently rewrite the record it references.

### Check, audit, and export

```text
/memory-hub status
/memory-hub dream
/memory-hub export
/memory-hub export decisions
/memory-hub export session <SESSION_ID>
```

`status` reports recent activity, active decisions, open work, feedback, and unconfirmed memories.

`dream` audits the memory store. By default it is a dry run that reports index issues, dangling references, relationship inconsistencies, and exact duplicate candidates. After you approve the report, `/memory-hub dream apply` can rebuild the search index and make mechanically safe repairs. It does not merge similar records, delete history, or invent rationale.

`export` writes browsable Markdown under `.memory-hub/exports/`. SQLite remains authoritative, so editing an export does not change stored memory.

## Installation options

Memory Hub follows the open [Agent Skills](https://agentskills.io) format. Install the complete `skills/memory-hub/` directory, not only `SKILL.md`; the skill also needs its `scripts/`, `references/`, and `assets/` directories.

Review third-party skills before allowing shell commands. Memory Hub needs shell access in full mode to run its bundled Python script and inspect Git state.

### skills.sh

The recommended installer is [skills.sh](https://skills.sh):

```bash
npx skills@latest add <OWNER>/memory-hub-skill
```

The installer detects supported agents and lets you choose project or personal scope.

### GitHub Copilot

Project installations are discovered in:

```text
.github/skills/memory-hub/
.agents/skills/memory-hub/
.claude/skills/memory-hub/
```

Personal installations can use:

```text
~/.copilot/skills/memory-hub/
~/.agents/skills/memory-hub/
```

GitHub CLI 2.90.0 or newer can install a published skill:

```bash
gh skill preview <OWNER>/memory-hub-skill memory-hub
gh skill install <OWNER>/memory-hub-skill memory-hub
```

Copilot CLI uses the same personal directories. Start a new CLI session after installation so the skill is discovered.

### OpenCode

Project installations are discovered in:

```text
.opencode/skills/memory-hub/
.agents/skills/memory-hub/
.claude/skills/memory-hub/
```

Global installations can use:

```text
~/.config/opencode/skills/memory-hub/
~/.agents/skills/memory-hub/
~/.claude/skills/memory-hub/
```

Restart OpenCode after installation. If your permission settings restrict skills or shell commands, allow `memory-hub` and approve its Python and Git operations.

### Claude Code

Use `.claude/skills/memory-hub/` for one project or `~/.claude/skills/memory-hub/` for all projects. You can select Claude Code in the skills.sh installer or place the complete skill directory there manually.

### Codex and other compatible agents

Many Agent Skills-compatible tools use:

```text
.agents/skills/memory-hub/
~/.agents/skills/memory-hub/
```

The skills.sh installer also supports hosts such as Codex, Cursor, Windsurf, and Gemini CLI. Choose the project path to keep memory tooling scoped to one repository or the home path to make the skill available across projects.

After installation, the skill directory should look like this:

```text
memory-hub/
|-- SKILL.md
|-- scripts/memory_hub.py
|-- references/
`-- assets/web/
```

## Requirements and reduced mode

Full mode requires:

- Python 3.10 or newer
- Git for repository metadata and change verification
- An agent that supports the Agent Skills format
- Permission for the agent to run the bundled Python script

Without Python, Git, or shell access, Memory Hub can still prepare a structured capture and Markdown summary in the conversation. It cannot persist or retrieve SQLite memory, verify Git state, export the database, or run the browser. The agent will say when it has switched to this reduced mode.

## Storage and privacy

Repository memory lives under:

```text
.memory-hub/
|-- memory.db
|-- config.json
|-- exports/
`-- server.json
```

`memory.db` is the source of truth. Exports are generated views, and `server.json` identifies the local browser process so Memory Hub can stop only the server it started.

Memory Hub is local-first. It has no required cloud account, cloud synchronization, or telemetry. It stores extracted knowledge rather than raw transcripts. Suspected secrets should be redacted before capture.

You decide whether `.memory-hub/` stays untracked or whether selected Markdown exports belong in version control. The SQLite database may contain internal project context, so review it before sharing.

## Technical reference

Memory Hub uses capture schema version 1. Captures can contain sessions, tasks, changes, decisions, directions, capabilities, open loops, evidence, and relationships. Provenance and confirmation fields keep agent interpretations separate from observed and human-confirmed facts.

Feedback uses a separate payload and can reference the repository, a session, or a memory record without mutating that target.

- [SKILL.md](skills/memory-hub/SKILL.md) defines the executable agent contract.
- [Capture schema](skills/memory-hub/references/capture-schema.md) documents version 1 JSON.
- [Memory types](skills/memory-hub/references/memory-types.md) explains semantics and authority.
- [Workflows](skills/memory-hub/references/workflows.md) covers actions and failure behavior.

The repository keeps each installable skill self-contained:

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

## Development

The runtime and tests use only the Python standard library:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/memory-hub/scripts/memory_hub.py
node --check skills/memory-hub/assets/web/app.js
```

## License

[MIT](LICENSE)
