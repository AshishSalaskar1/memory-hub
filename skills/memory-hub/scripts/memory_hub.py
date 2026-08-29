#!/usr/bin/env python3
"""Local, dependency-free runtime for the Memory Hub skill."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import urllib.error
import urllib.request
import uuid


APP_VERSION = "1.0"
# Capture payloads remain version 1; database migrations are versioned separately.
SCHEMA_VERSION = 1
DB_SCHEMA_VERSION = 3
DEFAULT_MAX_CHARS = 12_000
MAX_JSON_BODY = 1024 * 1024
TOP_ARRAYS = (
    "checkpoints", "tasks", "changes", "decisions", "directions",
    "capabilities", "open_loops", "evidence", "relationships",
)
ENTITY_TABLES = TOP_ARRAYS[:-1]
PREFIXES = {
    "sessions": "ses", "checkpoints": "chk", "tasks": "tsk",
    "changes": "chg", "decisions": "dec", "directions": "dir",
    "capabilities": "cap", "open_loops": "lop", "evidence": "evd",
    "relationships": "rel",
    "feedback": "fdb",
}
JSON_COLUMNS = {
    "tasks": {"tests", "file_paths", "evidence_ids"},
    "changes": {"task_ids", "evidence_ids"},
    "decisions": {"rationale", "alternatives", "tradeoffs", "reconsider_when", "evidence_ids"},
    "directions": {"evidence_ids"},
    "capabilities": {"file_paths", "test_paths", "limitations", "evidence_ids"},
    "open_loops": {"evidence_ids"},
    "checkpoints": {"evidence_ids", "git_changed_files"},
    "evidence": {"evidence_ids"},
    "sessions": {"git_changed_files"},
}


class MemoryHubError(Exception):
    pass


class ValidationError(MemoryHubError):
    pass


class NotFoundError(MemoryHubError):
    pass


class ConflictError(MemoryHubError):
    pass


class PayloadTooLargeError(MemoryHubError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def public_id(table: str) -> str:
    return f"{PREFIXES[table]}_{uuid.uuid4().hex[:16]}"


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True,
            timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # NUL-delimited porcelain uses leading spaces as part of its status code.
    return result.stdout if "-z" in args else result.stdout.strip()


def discover_repo(value: str | None) -> Path:
    start = Path(value or os.getcwd()).expanduser()
    try:
        root = start.resolve(strict=True)
    except OSError as exc:
        raise MemoryHubError(f"repository root does not exist: {start}") from exc
    if not root.is_dir():
        raise MemoryHubError(f"repository root is not a directory: {root}")
    if value:
        return root
    git_root = run_git(root, "rev-parse", "--show-toplevel")
    if git_root:
        return Path(git_root).resolve()
    for candidate in (root, *root.parents):
        if (candidate / ".memory-hub").is_dir():
            return candidate
    return root


def paths(root: Path) -> tuple[Path, Path, Path, Path]:
    hub = root / ".memory-hub"
    return hub, hub / "memory.db", hub / "config.json", hub / "server.json"


def require_initialized(root: Path) -> Path:
    database = paths(root)[1]
    if not database.is_file():
        raise MemoryHubError(f"Memory Hub is not initialized at {root}; run init first")
    return database


def git_metadata(root: Path) -> dict[str, object]:
    inside = run_git(root, "rev-parse", "--is-inside-work-tree") == "true"
    if not inside:
        return {"available": False, "branch": None, "head": None, "dirty": None, "changed_files": []}
    branch = run_git(root, "branch", "--show-current") or run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = run_git(root, "rev-parse", "HEAD")
    raw = run_git(root, "status", "--porcelain=v1", "-z")
    changed: list[dict[str, str]] = []
    if raw is not None:
        entries = raw.split("\0")
        index = 0
        while index < len(entries) and entries[index]:
            item = entries[index]
            code, name = item[:2], item[3:]
            record = {"status": code, "path": name}
            if code[0] in "RC" and index + 1 < len(entries):
                index += 1
                record = {"status": code, "path": name, "old_path": entries[index]}
            changed.append(record)
            index += 1
    return {
        "available": True, "branch": branch, "head": head,
        "dirty": bool(changed), "changed_files": changed,
    }


def git_change_kind(status: str) -> str:
    if status == "??":
        return "untracked"
    if "R" in status:
        return "renamed"
    if "D" in status:
        return "deleted"
    if "A" in status:
        return "added"
    return "modified"


MIGRATION_1 = """
CREATE TABLE repositories (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, root_path TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, initialized_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 git_available INTEGER NOT NULL, git_branch TEXT, git_head TEXT, git_dirty INTEGER,
 git_changed_files TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE sessions (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 agent TEXT, model TEXT, goal TEXT NOT NULL, outcome TEXT NOT NULL, summary TEXT NOT NULL,
 status TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT,
 git_branch TEXT, git_head TEXT, git_dirty INTEGER, git_changed_files TEXT NOT NULL DEFAULT '[]'
);
CREATE UNIQUE INDEX one_active_session ON sessions(repository_id) WHERE status='active';
CREATE INDEX sessions_repository_time ON sessions(repository_id, updated_at DESC);
CREATE TABLE checkpoints (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), summary TEXT NOT NULL, open_context TEXT,
 scope TEXT, source TEXT, confidence TEXT, confirmation TEXT, status TEXT,
 evidence_ids TEXT NOT NULL DEFAULT '[]', supersedes_id TEXT, superseded_by_id TEXT,
 created_at TEXT NOT NULL, git_branch TEXT, git_head TEXT, git_dirty INTEGER,
 git_changed_files TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE tasks (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), title TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
 result TEXT, tests TEXT NOT NULL DEFAULT '[]', file_paths TEXT NOT NULL DEFAULT '[]',
 scope TEXT, source TEXT, confidence TEXT, confirmation TEXT, evidence_ids TEXT NOT NULL DEFAULT '[]',
 supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE changes (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), path TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
 old_path TEXT, task_ids TEXT NOT NULL DEFAULT '[]', scope TEXT, source TEXT, confidence TEXT, confirmation TEXT,
 evidence_ids TEXT NOT NULL DEFAULT '[]', supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL,
 git_verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE decisions (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), title TEXT NOT NULL, status TEXT NOT NULL, scope TEXT NOT NULL,
 rationale TEXT NOT NULL, alternatives TEXT NOT NULL DEFAULT '[]', tradeoffs TEXT NOT NULL DEFAULT '[]',
 reconsider_when TEXT NOT NULL DEFAULT '[]', source TEXT, confidence TEXT, confirmation TEXT,
 evidence_ids TEXT NOT NULL DEFAULT '[]', supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE directions (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), instruction TEXT NOT NULL, status TEXT NOT NULL, scope TEXT NOT NULL,
 origin TEXT NOT NULL, importance TEXT NOT NULL, correction_of TEXT, source TEXT, confidence TEXT, confirmation TEXT,
 evidence_ids TEXT NOT NULL DEFAULT '[]', supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE capabilities (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), name TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
 file_paths TEXT NOT NULL DEFAULT '[]', test_paths TEXT NOT NULL DEFAULT '[]', limitations TEXT NOT NULL DEFAULT '[]',
 scope TEXT, source TEXT, confidence TEXT, confirmation TEXT, evidence_ids TEXT NOT NULL DEFAULT '[]',
 supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE open_loops (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), title TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
 summary TEXT NOT NULL, next_step TEXT, owner TEXT, scope TEXT, source TEXT, confidence TEXT, confirmation TEXT,
 evidence_ids TEXT NOT NULL DEFAULT '[]', supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE evidence (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), kind TEXT NOT NULL, summary TEXT NOT NULL,
 reference TEXT, observed_at TEXT, scope TEXT, source TEXT, confidence TEXT, confirmation TEXT,
 supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE relationships (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER NOT NULL REFERENCES sessions(id), from_id TEXT NOT NULL, type TEXT NOT NULL, to_id TEXT NOT NULL,
 summary TEXT, created_at TEXT NOT NULL, UNIQUE(repository_id, from_id, type, to_id)
);
CREATE INDEX checkpoints_session ON checkpoints(session_id, created_at DESC);
CREATE INDEX tasks_status ON tasks(repository_id, status, created_at DESC);
CREATE INDEX changes_path ON changes(repository_id, path, created_at DESC);
CREATE INDEX decisions_status ON decisions(repository_id, status, created_at DESC);
CREATE INDEX directions_status ON directions(repository_id, status, importance);
CREATE INDEX capabilities_status ON capabilities(repository_id, status, created_at DESC);
CREATE INDEX open_loops_status ON open_loops(repository_id, status, created_at DESC);
CREATE INDEX evidence_session ON evidence(session_id, created_at DESC);
CREATE INDEX relationships_from ON relationships(repository_id, from_id);
CREATE INDEX relationships_to ON relationships(repository_id, to_id);
"""

MIGRATION_2 = """
ALTER TABLE evidence ADD COLUMN evidence_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE evidence ADD COLUMN status TEXT;
ALTER TABLE changes ADD COLUMN status TEXT;
"""

MIGRATION_3 = """
CREATE TABLE feedback (
 id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE,
 repository_id INTEGER NOT NULL REFERENCES repositories(id),
 session_id INTEGER REFERENCES sessions(id), record_id TEXT,
 type TEXT NOT NULL, scope TEXT NOT NULL, sentiment TEXT NOT NULL,
 rating INTEGER, body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX feedback_repository_time ON feedback(repository_id, created_at DESC);
CREATE INDEX feedback_session ON feedback(session_id, created_at DESC);
CREATE INDEX feedback_record ON feedback(repository_id, record_id, created_at DESC);
"""


def connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def migrate(connection: sqlite3.Connection) -> bool:
    connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    for version, script in ((1, MIGRATION_1), (2, MIGRATION_2), (3, MIGRATION_3)):
        if version in applied:
            continue
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in script.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations VALUES(?, ?)", (version, now()))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    fts = True
    try:
        connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_type, public_id UNINDEXED, title, body)")
        connection.commit()
    except sqlite3.OperationalError:
        fts = False
    return fts


def repository_row(connection: sqlite3.Connection, root: Path) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM repositories WHERE root_path=?", (str(root),)).fetchone()
    if row is None:
        raise MemoryHubError("database does not contain this repository; run init")
    return row


def operation_init(root: Path) -> None:
    hub, database, config_path, _ = paths(root)
    hub.mkdir(mode=0o700, exist_ok=True)
    (hub / "exports").mkdir(exist_ok=True)
    metadata = git_metadata(root)
    connection = connect(database)
    try:
        fts = migrate(connection)
        stamp = now()
        with connection:
            connection.execute(
                """INSERT INTO repositories(public_id,root_path,name,initialized_at,updated_at,git_available,git_branch,git_head,git_dirty,git_changed_files)
                   VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root_path) DO UPDATE SET
                   updated_at=excluded.updated_at, git_available=excluded.git_available, git_branch=excluded.git_branch,
                   git_head=excluded.git_head, git_dirty=excluded.git_dirty, git_changed_files=excluded.git_changed_files""",
                (public_id("sessions").replace("ses_", "repo_"), str(root), root.name, stamp, stamp,
                 int(bool(metadata["available"])), metadata["branch"], metadata["head"],
                 None if metadata["dirty"] is None else int(bool(metadata["dirty"])), json_text(metadata["changed_files"])),
            )
    finally:
        connection.close()
    config = {
        "schema_version": SCHEMA_VERSION, "capture_schema_version": SCHEMA_VERSION,
        "db_schema_version": DB_SCHEMA_VERSION, "created_at": stamp,
        "repository_root": str(root), "database": "memory.db", "fts5": fts,
    }
    if config_path.exists():
        try:
            old = json.loads(config_path.read_text(encoding="utf-8"))
            config["created_at"] = old.get("created_at", stamp)
        except (OSError, ValueError):
            pass
    atomic_json(config_path, config)
    mode = "Git metadata recorded" if metadata["available"] else "Git metadata unavailable (non-Git directory)"
    print(f"Memory Hub initialized at {hub}\n{mode}\nDatabase: {database}")


COMMON = {"id", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes"}
SOURCES = {"observed", "agent", "human", "hypothesis", "future-intent"}
CONFIDENCES = {"high", "medium", "low"}
CONFIRMATIONS = {"human-confirmed", "explicit-human", "agent-inferred", "unconfirmed", "not-required"}
SPECS: dict[str, dict[str, object]] = {
    "checkpoints": {"required": {"summary"}, "optional": {"id", "summary", "open_context"} | COMMON},
    "tasks": {"required": {"title", "status", "summary"}, "optional": {"id", "title", "status", "summary", "result", "tests", "file_paths"} | COMMON,
              "status": {"planned", "in-progress", "completed", "blocked", "deferred", "abandoned"}},
    "changes": {"required": {"path", "kind", "summary"}, "optional": {"id", "path", "kind", "summary", "old_path", "task_ids"} | COMMON,
                "kind": {"added", "modified", "deleted", "renamed", "untracked"}},
    "decisions": {"required": {"title", "status", "scope", "rationale"}, "optional": {"id", "title", "status", "scope", "rationale", "alternatives", "tradeoffs", "reconsider_when"} | COMMON,
                  "status": {"proposed", "active", "rejected", "superseded", "needs-review"}},
    "directions": {"required": {"instruction", "status", "scope", "origin", "importance"}, "optional": {"id", "instruction", "status", "scope", "origin", "importance", "correction_of"} | COMMON,
                   "status": {"active", "superseded"}, "origin": {"human", "agent"}, "importance": {"high", "medium", "low"}},
    "capabilities": {"required": {"name", "status", "summary"}, "optional": {"id", "name", "status", "summary", "file_paths", "test_paths", "limitations"} | COMMON,
                     "status": {"planned", "partial", "implemented", "deprecated"}},
    "open_loops": {"required": {"title", "kind", "status", "summary"}, "optional": {"id", "title", "kind", "status", "summary", "next_step", "owner"} | COMMON,
                   "kind": {"unfinished-work", "blocker", "question", "deferred-refactor", "missing-test", "workaround"},
                   "status": {"open", "blocked", "deferred", "resolved"}},
    "evidence": {"required": {"id", "kind", "summary"}, "optional": {"id", "kind", "summary", "reference", "observed_at"} | COMMON,
                 "kind": {"git", "file", "test", "tool-output", "human-statement", "agent-context"}},
    "relationships": {"required": {"from_id", "type", "to_id"}, "optional": {"from_id", "type", "to_id", "summary"},
                      "type": {"supports", "implements", "affects", "depends-on", "blocks", "resolves", "supersedes", "evidenced-by", "belongs-to", "related-to"}},
}
ARRAY_FIELDS = {"evidence_ids", "tests", "file_paths", "task_ids", "rationale", "alternatives", "tradeoffs", "reconsider_when", "test_paths", "limitations"}
PATH_FIELDS = {"path", "old_path", "file_paths", "test_paths"}
SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I)),
    ("service token", re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b")),
    ("credential assignment", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\b\s*[:=]\s*[\"']?[^\s\"']{8,}")),
    ("authorization credential", re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")),
]


def fail(path: str, message: str) -> None:
    raise ValidationError(f"{path}: {message}")


def string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(path, "expected a non-empty string")
    if value != value.strip():
        fail(path, "string must be trimmed")
    return value


def safe_path(value: object, field: str) -> str:
    item = string(value, field)
    normalized = item.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or item.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:/", normalized) or ".." in candidate.parts or "\x00" in item:
        fail(field, "expected a safe repository-relative path")
    if normalized in {"", "."}:
        fail(field, "expected a file path")
    return normalized


def stable_type(connection: sqlite3.Connection, repository_id: int, identifier: str) -> str | None:
    if identifier.startswith("ses_"):
        if connection.execute("SELECT 1 FROM sessions WHERE repository_id=? AND public_id=?", (repository_id, identifier)).fetchone():
            return "sessions"
        return None
    for table in ENTITY_TABLES:
        if identifier.startswith(PREFIXES[table] + "_"):
            if connection.execute(f"SELECT 1 FROM {table} WHERE repository_id=? AND public_id=?", (repository_id, identifier)).fetchone():
                return table
    return None


def detect_secret(payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(serialized):
            raise ValidationError(f"payload: suspected {label}; capture rejected before persistence (redact the secret and retry)")


def validate_payload(payload: object, connection: sqlite3.Connection, repository_id: int) -> dict[str, object]:
    if not isinstance(payload, dict):
        fail("payload", "expected a JSON object")
    detect_secret(payload)
    expected_top = {"schema_version", "session", *TOP_ARRAYS}
    unknown = set(payload) - expected_top
    missing = expected_top - set(payload)
    if unknown:
        fail(next(iter(sorted(unknown))), "unknown top-level field")
    if missing:
        fail(next(iter(sorted(missing))), "required field is missing")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        fail("schema_version", "expected integer 1")
    session = payload["session"]
    if not isinstance(session, dict):
        fail("session", "expected an object")
    session_allowed = {"mode", "agent", "model", "goal", "outcome", "summary"}
    unknown_session = set(session) - session_allowed
    if unknown_session:
        fail(f"session.{next(iter(sorted(unknown_session)))}", "unknown field")
    for field in ("mode", "goal", "outcome", "summary"):
        if field not in session:
            fail(f"session.{field}", "required field is missing")
    for field, value in session.items():
        string(value, f"session.{field}")
    if session["mode"] not in {"checkpoint", "close"}:
        fail("session.mode", "expected checkpoint|close")
    outcomes = {"completed", "partial", "blocked", "abandoned", "unknown"}
    if session["outcome"] not in outcomes:
        fail("session.outcome", f"expected {'|'.join(sorted(outcomes))}")

    local_ids: dict[str, str] = {}
    pending_refs: list[tuple[str, str, str | None]] = []
    for table in TOP_ARRAYS:
        records = payload[table]
        if not isinstance(records, list):
            fail(table, "expected an array")
        spec = SPECS[table]
        for index, record in enumerate(records):
            base = f"{table}[{index}]"
            if not isinstance(record, dict):
                fail(base, "expected an object")
            unknown_fields = set(record) - spec["optional"]
            if unknown_fields:
                fail(f"{base}.{next(iter(sorted(unknown_fields)))}", "unknown field")
            for required in spec["required"]:
                if required not in record:
                    fail(f"{base}.{required}", "required field is missing")
            for field, value in record.items():
                field_path = f"{base}.{field}"
                if field in ARRAY_FIELDS:
                    if not isinstance(value, list):
                        fail(field_path, "expected an array of non-empty strings")
                    if field == "rationale" and not value:
                        fail(field_path, "expected at least one rationale")
                    for item_index, item in enumerate(value):
                        string(item, f"{field_path}[{item_index}]")
                elif field not in {"evidence_ids", "task_ids"}:
                    string(value, field_path)
                if field in PATH_FIELDS:
                    if isinstance(value, list):
                        for item_index, item in enumerate(value):
                            safe_path(item, f"{field_path}[{item_index}]")
                    else:
                        safe_path(value, field_path)
            for enum_field in ("status", "kind", "origin", "importance", "type"):
                if enum_field in record and enum_field in spec and record[enum_field] not in spec[enum_field]:
                    fail(f"{base}.{enum_field}", f"expected {'|'.join(sorted(spec[enum_field]))}")
            if "source" in record and record["source"] not in SOURCES:
                fail(f"{base}.source", f"expected {'|'.join(sorted(SOURCES))}")
            if "confidence" in record and record["confidence"] not in CONFIDENCES:
                fail(f"{base}.confidence", f"expected {'|'.join(sorted(CONFIDENCES))}")
            if "confirmation" in record and record["confirmation"] not in CONFIRMATIONS:
                fail(f"{base}.confirmation", f"expected {'|'.join(sorted(CONFIRMATIONS))}")
            if record.get("confirmation") in {"human-confirmed", "explicit-human"} and record.get("source") != "human":
                fail(f"{base}.confirmation", "human confirmation requires source 'human'")
            if table == "capabilities" and record.get("status") == "implemented" and not (
                record.get("file_paths") or record.get("test_paths") or record.get("evidence_ids")
            ):
                fail(f"{base}.status", "implemented requires file_paths, test_paths, or evidence_ids")
            local = record.get("id")
            if local:
                if local in local_ids:
                    fail(f"{base}.id", f"duplicate capture-local ID '{local}'")
                local_ids[local] = table
            for ref_field in ("evidence_ids", "task_ids", "supersedes", "correction_of"):
                refs = record.get(ref_field, [])
                if isinstance(refs, str):
                    refs = [refs]
                for ref_index, ref in enumerate(refs):
                    suffix = f"[{ref_index}]" if isinstance(record.get(ref_field), list) else ""
                    expected_type = "evidence" if ref_field == "evidence_ids" else "tasks" if ref_field == "task_ids" else table if ref_field == "supersedes" else None
                    pending_refs.append((f"{base}.{ref_field}{suffix}", ref, expected_type))
    for path_name, reference, expected_type in pending_refs:
        resolved_type = local_ids.get(reference) or stable_type(connection, repository_id, reference)
        if resolved_type is None:
            fail(path_name, f"unknown local or stable ID '{reference}'")
        if expected_type and resolved_type != expected_type:
            fail(path_name, f"expected an ID for {expected_type}, got {resolved_type}")
    for index, relationship in enumerate(payload["relationships"]):
        for field in ("from_id", "to_id"):
            reference = relationship[field]
            if reference not in local_ids and not stable_type(connection, repository_id, reference):
                fail(f"relationships[{index}].{field}", f"unknown local or stable ID '{reference}'")
        if relationship["from_id"] == relationship["to_id"] and relationship["type"] == "supersedes":
            fail(f"relationships[{index}]", "a record cannot supersede itself")
    relationship_keys: set[tuple[str, str, str]] = set()
    for index, relationship in enumerate(payload["relationships"]):
        key = (relationship["from_id"], relationship["type"], relationship["to_id"])
        if key in relationship_keys:
            fail(f"relationships[{index}]", "duplicate relationship")
        relationship_keys.add(key)
    for table in ENTITY_TABLES:
        for index, record in enumerate(payload[table]):
            if record.get("id") and record.get("supersedes") == record["id"]:
                fail(f"{table}[{index}].supersedes", "a record cannot supersede itself")
    return payload


TABLE_COLUMNS = {
    "checkpoints": ["summary", "open_context", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes_id"],
    "tasks": ["title", "status", "summary", "result", "tests", "file_paths", "scope", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    "changes": ["path", "kind", "summary", "old_path", "task_ids", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes_id"],
    "decisions": ["title", "status", "scope", "rationale", "alternatives", "tradeoffs", "reconsider_when", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    "directions": ["instruction", "status", "scope", "origin", "importance", "correction_of", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    "capabilities": ["name", "status", "summary", "file_paths", "test_paths", "limitations", "scope", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    "open_loops": ["title", "kind", "status", "summary", "next_step", "owner", "scope", "source", "confidence", "confirmation", "evidence_ids", "supersedes_id"],
    "evidence": ["kind", "summary", "reference", "observed_at", "scope", "source", "confidence", "confirmation", "status", "evidence_ids", "supersedes_id"],
}

TYPE_ALIASES = {
    alias: table
    for table in ENTITY_TABLES
    for alias in (table, table[:-3] + "y" if table.endswith("ies") else table[:-1] if table.endswith("s") else table)
}
TYPE_ALIASES["open_loop"] = "open_loops"
TYPE_ALIASES["feedback"] = "feedback"
EDITABLE_FIELDS = {
    table: set(spec["optional"]) - {"id"}
    for table, spec in SPECS.items()
    if table in ENTITY_TABLES
}
EDITABLE_FIELDS["feedback"] = {"type", "sentiment", "rating", "body"}

FEEDBACK_TYPES = {"positive", "correction", "concern", "suggestion"}
FEEDBACK_SCOPES = {"repository", "session", "record"}
FEEDBACK_SENTIMENTS = {"positive", "neutral", "negative"}


def validate_feedback(
    payload: object, connection: sqlite3.Connection, repository_id: int,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        fail("payload", "expected a JSON object")
    detect_secret(payload)
    allowed = {"type", "scope", "sentiment", "rating", "session_id", "record_id", "body"}
    unknown = set(payload) - allowed
    if unknown:
        fail(next(iter(sorted(unknown))), "unknown field")
    for field in ("type", "scope", "sentiment", "body"):
        if field not in payload:
            fail(field, "required field is missing")
    for field, choices in (("type", FEEDBACK_TYPES), ("scope", FEEDBACK_SCOPES), ("sentiment", FEEDBACK_SENTIMENTS)):
        value = string(payload[field], field)
        if value not in choices:
            fail(field, f"expected {'|'.join(sorted(choices))}")
    body = string(payload["body"], "body")
    rating = payload.get("rating")
    if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
        fail("rating", "expected an integer from 1 through 5 (boolean values are not valid)")
    session_identifier = payload.get("session_id")
    record_identifier = payload.get("record_id")
    scope = str(payload["scope"])
    if scope == "repository":
        if "session_id" in payload or "record_id" in payload:
            fail("scope", "repository feedback must not include session_id or record_id")
        session_db_id = None
    elif scope == "session":
        if "session_id" not in payload:
            fail("session_id", "required when scope is 'session'")
        if "record_id" in payload:
            fail("record_id", "must not be included when scope is 'session'")
        session_identifier = string(session_identifier, "session_id")
        session = connection.execute(
            "SELECT id FROM sessions WHERE repository_id=? AND public_id=?",
            (repository_id, session_identifier),
        ).fetchone()
        if session is None:
            fail("session_id", f"unknown session ID '{session_identifier}' in this repository")
        session_db_id = session["id"]
    else:
        if "record_id" not in payload:
            fail("record_id", "required when scope is 'record'")
        record_identifier = string(record_identifier, "record_id")
        target_type = stable_type(connection, repository_id, record_identifier)
        if target_type not in ENTITY_TABLES:
            fail("record_id", f"unknown capture record ID '{record_identifier}' in this repository; sessions and feedback are not record targets")
        target = connection.execute(
            f"SELECT session_id FROM {target_type} WHERE repository_id=? AND public_id=?",
            (repository_id, record_identifier),
        ).fetchone()
        session_db_id = target["session_id"]
        owner = connection.execute("SELECT public_id FROM sessions WHERE id=?", (session_db_id,)).fetchone()[0]
        if "session_id" in payload:
            session_identifier = string(session_identifier, "session_id")
            if session_identifier != owner:
                fail("session_id", f"record '{record_identifier}' belongs to session '{owner}', not '{session_identifier}'")
        session_identifier = owner
    return {
        "type": payload["type"], "scope": scope, "sentiment": payload["sentiment"],
        "rating": rating, "body": body, "session_id": session_identifier,
        "record_id": record_identifier, "_session_db_id": session_db_id,
    }


def validate_feedback_patch(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        fail("payload", "expected a JSON object")
    if not payload:
        fail("payload", "expected at least one editable field")
    detect_secret(payload)
    unknown = set(payload) - EDITABLE_FIELDS["feedback"]
    if unknown:
        fail(next(iter(sorted(unknown))), "unknown or immutable field; scope, session_id, and record_id cannot be changed")
    if "type" in payload:
        value = string(payload["type"], "type")
        if value not in FEEDBACK_TYPES:
            fail("type", f"expected {'|'.join(sorted(FEEDBACK_TYPES))}")
    if "sentiment" in payload:
        value = string(payload["sentiment"], "sentiment")
        if value not in FEEDBACK_SENTIMENTS:
            fail("sentiment", f"expected {'|'.join(sorted(FEEDBACK_SENTIMENTS))}")
    if "body" in payload:
        string(payload["body"], "body")
    if "rating" in payload and payload["rating"] is not None and (
        type(payload["rating"]) is not int or not 1 <= payload["rating"] <= 5
    ):
        fail("rating", "expected null or an integer from 1 through 5 (boolean values are not valid)")
    return payload


def resolve_id(reference: str | None, id_map: dict[str, str]) -> str | None:
    return id_map.get(reference, reference) if reference else None


def fts_add(connection: sqlite3.Connection, table: str, identifier: str, record: dict[str, object]) -> None:
    title = str(record.get("title") or record.get("name") or record.get("instruction") or record.get("path") or record.get("summary") or "")
    body = " ".join(str(value) if not isinstance(value, list) else " ".join(value) for value in record.values() if value)
    try:
        connection.execute("INSERT INTO memory_fts(memory_type,public_id,title,body) VALUES(?,?,?,?)", (table, identifier, title, body))
    except sqlite3.OperationalError:
        pass


def fts_replace(connection: sqlite3.Connection, table: str, identifier: str, record: dict[str, object]) -> None:
    try:
        connection.execute("DELETE FROM memory_fts WHERE memory_type=? AND public_id=?", (table, identifier))
    except sqlite3.OperationalError:
        return
    fts_add(connection, table, identifier, record)


def validate_record_patch(
    connection: sqlite3.Connection, repository_id: int, table: str,
    current: dict[str, object], patch: object,
) -> dict[str, object]:
    if not isinstance(patch, dict):
        fail("payload", "expected a JSON object")
    if not patch:
        fail("payload", "expected at least one field")
    detect_secret(patch)
    unknown = set(patch) - EDITABLE_FIELDS[table]
    if unknown:
        fail(next(iter(sorted(unknown))), "unknown or immutable field")
    merged = dict(current)
    merged["supersedes"] = merged.pop("supersedes_id", None)
    merged.update(patch)
    spec = SPECS[table]
    for field in spec["required"]:
        if not merged.get(field):
            fail(field, "required field must remain a non-empty value")
    for field, value in patch.items():
        if field in ARRAY_FIELDS:
            if not isinstance(value, list):
                fail(field, "expected an array of non-empty strings")
            if field == "rationale" and not value:
                fail(field, "expected at least one rationale")
            for index, item in enumerate(value):
                string(item, f"{field}[{index}]")
        elif field not in {"evidence_ids", "task_ids"}:
            string(value, field)
        if field in PATH_FIELDS:
            values = value if isinstance(value, list) else [value]
            for index, item in enumerate(values):
                safe_path(item, f"{field}[{index}]" if isinstance(value, list) else field)
        if field in spec and field in {"status", "kind", "origin", "importance", "type"} and value not in spec[field]:
            fail(field, f"expected {'|'.join(sorted(spec[field]))}")
    if "source" in patch and patch["source"] not in SOURCES:
        fail("source", f"expected {'|'.join(sorted(SOURCES))}")
    if "confidence" in patch and patch["confidence"] not in CONFIDENCES:
        fail("confidence", f"expected {'|'.join(sorted(CONFIDENCES))}")
    if "confirmation" in patch and patch["confirmation"] not in CONFIRMATIONS:
        fail("confirmation", f"expected {'|'.join(sorted(CONFIRMATIONS))}")
    if merged.get("confirmation") in {"human-confirmed", "explicit-human"} and merged.get("source") != "human":
        fail("confirmation", "human confirmation requires source 'human'")
    if table == "capabilities" and merged.get("status") == "implemented" and not (
        merged.get("file_paths") or merged.get("test_paths") or merged.get("evidence_ids")
    ):
        fail("status", "implemented requires file_paths, test_paths, or evidence_ids")
    for field in ("evidence_ids", "task_ids", "supersedes", "correction_of"):
        if field not in patch:
            continue
        references = patch[field] if isinstance(patch[field], list) else [patch[field]]
        expected = "evidence" if field == "evidence_ids" else "tasks" if field == "task_ids" else table if field == "supersedes" else None
        for index, reference in enumerate(references):
            string(reference, f"{field}[{index}]" if isinstance(patch[field], list) else field)
            found = stable_type(connection, repository_id, reference)
            if found is None:
                fail(field, f"unknown stable ID '{reference}'")
            if expected and found != expected:
                fail(field, f"expected an ID for {expected}, got {found}")
            if field == "supersedes" and reference == current["id"]:
                fail(field, "a record cannot supersede itself")
    return patch


def operation_capture(root: Path, input_path: Path) -> None:
    database = require_initialized(root)
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MemoryHubError(f"cannot read capture input {input_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"payload: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    connection = connect(database)
    try:
        migrate(connection)
        repository = repository_row(connection, root)
        payload = validate_payload(payload, connection, repository["id"])
        metadata = git_metadata(root)
        stamp = now()
        counts = {table: len(payload[table]) for table in TOP_ARRAYS}
        with connection:
            active = connection.execute(
                "SELECT * FROM sessions WHERE repository_id=? AND status='active'", (repository["id"],)
            ).fetchone()
            session_data = payload["session"]
            if active is None:
                sid = public_id("sessions")
                cursor = connection.execute(
                    """INSERT INTO sessions(public_id,repository_id,agent,model,goal,outcome,summary,status,started_at,updated_at,closed_at,git_branch,git_head,git_dirty,git_changed_files)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, repository["id"], session_data.get("agent"), session_data.get("model"), session_data["goal"],
                     session_data["outcome"], session_data["summary"], "closed" if session_data["mode"] == "close" else "active",
                     stamp, stamp, stamp if session_data["mode"] == "close" else None, metadata["branch"], metadata["head"],
                     None if metadata["dirty"] is None else int(bool(metadata["dirty"])), json_text(metadata["changed_files"])),
                )
                session_db_id = cursor.lastrowid
            else:
                sid, session_db_id = active["public_id"], active["id"]
                connection.execute(
                    """UPDATE sessions SET agent=COALESCE(?,agent),model=COALESCE(?,model),goal=?,outcome=?,summary=?,
                       status=?,updated_at=?,closed_at=?,git_branch=?,git_head=?,git_dirty=?,git_changed_files=? WHERE id=?""",
                    (session_data.get("agent"), session_data.get("model"), session_data["goal"], session_data["outcome"],
                     session_data["summary"], "closed" if session_data["mode"] == "close" else "active", stamp,
                     stamp if session_data["mode"] == "close" else None, metadata["branch"], metadata["head"],
                     None if metadata["dirty"] is None else int(bool(metadata["dirty"])), json_text(metadata["changed_files"]), session_db_id),
                )
            id_map: dict[str, str] = {}
            generated: dict[tuple[str, int], str] = {}
            for table in ENTITY_TABLES:
                for index, record in enumerate(payload[table]):
                    identifier = public_id(table)
                    generated[(table, index)] = identifier
                    if record.get("id"):
                        id_map[record["id"]] = identifier
            for table in ENTITY_TABLES:
                records = payload[table]
                if table == "checkpoints" and session_data["mode"] == "checkpoint" and not records:
                    records = [{"summary": session_data["summary"], "open_context": session_data["summary"]}]
                    generated[(table, 0)] = public_id(table)
                    counts[table] = 1
                for index, source_record in enumerate(records):
                    record = dict(source_record)
                    identifier = generated[(table, index)]
                    record["supersedes_id"] = resolve_id(record.pop("supersedes", None), id_map)
                    if "correction_of" in record:
                        record["correction_of"] = resolve_id(record["correction_of"], id_map)
                    for ref_field in ("evidence_ids", "task_ids"):
                        if ref_field in record:
                            record[ref_field] = [resolve_id(item, id_map) for item in record[ref_field]]
                    columns = TABLE_COLUMNS[table]
                    values: list[object] = []
                    for column in columns:
                        value = record.get(column)
                        if column in JSON_COLUMNS.get(table, set()):
                            value = json_text(value or [])
                        values.append(value)
                    extra_columns: list[str] = []
                    extra_values: list[object] = []
                    if table == "checkpoints":
                        extra_columns = ["git_branch", "git_head", "git_dirty", "git_changed_files"]
                        extra_values = [metadata["branch"], metadata["head"], None if metadata["dirty"] is None else int(bool(metadata["dirty"])), json_text(metadata["changed_files"])]
                    elif table == "changes":
                        changed_by_path = {item["path"]: item for item in metadata["changed_files"]}
                        git_change = changed_by_path.get(record["path"])
                        verified = bool(
                            git_change
                            and record["kind"] == git_change_kind(git_change["status"])
                            and (record["kind"] != "renamed" or record.get("old_path") == git_change.get("old_path"))
                        )
                        extra_columns = ["git_verified"]
                        extra_values = [int(verified)]
                    all_columns = ["public_id", "repository_id", "session_id", *columns, "created_at", *extra_columns]
                    placeholders = ",".join("?" for _ in all_columns)
                    connection.execute(
                        f"INSERT INTO {table}({','.join(all_columns)}) VALUES({placeholders})",
                        [identifier, repository["id"], session_db_id, *values, stamp, *extra_values],
                    )
                    fts_add(connection, table, identifier, record)
            # Apply links after every capture-local record exists, so array order is irrelevant.
            for table in ENTITY_TABLES:
                for index, source_record in enumerate(payload[table]):
                    supersedes = resolve_id(source_record.get("supersedes"), id_map)
                    if not supersedes:
                        continue
                    identifier = generated[(table, index)]
                    result = connection.execute(
                        f"UPDATE {table} SET superseded_by_id=? WHERE repository_id=? AND public_id=?",
                        (identifier, repository["id"], supersedes),
                    )
                    if result.rowcount and table in {"decisions", "directions"}:
                        connection.execute(f"UPDATE {table} SET status='superseded' WHERE public_id=?", (supersedes,))
            for relationship in payload["relationships"]:
                from_id = resolve_id(relationship["from_id"], id_map)
                to_id = resolve_id(relationship["to_id"], id_map)
                connection.execute(
                    "INSERT OR IGNORE INTO relationships(public_id,repository_id,session_id,from_id,type,to_id,summary,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (public_id("relationships"), repository["id"], session_db_id, from_id, relationship["type"], to_id, relationship.get("summary"), stamp),
                )
            connection.execute(
                """UPDATE repositories SET updated_at=?,git_available=?,git_branch=?,git_head=?,git_dirty=?,git_changed_files=? WHERE id=?""",
                (stamp, int(bool(metadata["available"])), metadata["branch"], metadata["head"],
                 None if metadata["dirty"] is None else int(bool(metadata["dirty"])), json_text(metadata["changed_files"]), repository["id"]),
            )
        count_text = ", ".join(f"{name}={value}" for name, value in counts.items() if value)
        print(f"Captured session {sid} ({session_data['mode']})" + (f"\nStored: {count_text}" if count_text else "\nStored: session only"))
        if not metadata["available"]:
            print("Warning: Git metadata unavailable; file changes were not verified", file=sys.stderr)
    finally:
        connection.close()


def create_feedback(root: Path, payload: object) -> dict[str, object]:
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        repository = repository_row(connection, root)
        feedback = validate_feedback(payload, connection, repository["id"])
        identifier = public_id("feedback")
        stamp = now()
        with connection:
            connection.execute(
                """INSERT INTO feedback(public_id,repository_id,session_id,record_id,type,scope,sentiment,rating,body,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (identifier, repository["id"], feedback.pop("_session_db_id"), feedback["record_id"],
                 feedback["type"], feedback["scope"], feedback["sentiment"], feedback["rating"], feedback["body"], stamp),
            )
            fts_add(connection, "feedback", identifier, feedback)
        return get_record(connection, repository["id"], "feedback", identifier)
    finally:
        connection.close()


def operation_feedback(root: Path, input_path: Path) -> None:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MemoryHubError(f"cannot read feedback input {input_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"payload: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    feedback = create_feedback(root, payload)
    print(f"Stored feedback {feedback['id']} (scope={feedback['scope']})")


def decode_row(table: str, row: sqlite3.Row | dict[str, object]) -> dict[str, object]:
    result = dict(row)
    result.pop("id", None)
    result.pop("repository_id", None)
    for column in JSON_COLUMNS.get(table, set()):
        if column in result:
            try:
                result[column] = json.loads(result[column] or "[]")
            except (TypeError, json.JSONDecodeError):
                result[column] = []
    if "public_id" in result:
        result["id"] = result.pop("public_id")
    return result


def decode_feedback(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    result = decode_row("feedback", row)
    internal_session_id = result.pop("session_id", None)
    if internal_session_id is not None:
        session = connection.execute("SELECT public_id FROM sessions WHERE id=?", (internal_session_id,)).fetchone()
        result["session_id"] = session[0] if session else None
    else:
        result["session_id"] = None
    return result


def rows(connection: sqlite3.Connection, table: str, where: str = "1", params: tuple[object, ...] = (), limit: int | None = None) -> list[dict[str, object]]:
    sql = f"SELECT * FROM {table} WHERE {where} ORDER BY created_at DESC"
    if table == "sessions":
        sql = f"SELECT * FROM sessions WHERE {where} ORDER BY updated_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    decoder = (lambda row: decode_feedback(connection, row)) if table == "feedback" else (lambda row: decode_row(table, row))
    return [decoder(row) for row in connection.execute(sql, params)]


def status_data(root: Path, connection: sqlite3.Connection) -> dict[str, object]:
    repo = repository_row(connection, root)
    rid = repo["id"]
    scalar = lambda sql, args=(): connection.execute(sql, args).fetchone()[0]
    return {
        "repository": repo["name"], "repository_root": str(root),
        "sessions": scalar("SELECT count(*) FROM sessions WHERE repository_id=?", (rid,)),
        "feedback": scalar("SELECT count(*) FROM feedback WHERE repository_id=?", (rid,)),
        "last_capture": scalar("SELECT max(updated_at) FROM sessions WHERE repository_id=?", (rid,)),
        "active_decisions": scalar("SELECT count(*) FROM decisions WHERE repository_id=? AND status='active'", (rid,)),
        "open_items": scalar("SELECT count(*) FROM open_loops WHERE repository_id=? AND superseded_by_id IS NULL AND status IN ('open','blocked','deferred')", (rid,)),
        "unconfirmed_memories": sum(scalar(f"SELECT count(*) FROM {table} WHERE repository_id=? AND confirmation IN ('unconfirmed','agent-inferred')", (rid,)) for table in ENTITY_TABLES if table != "evidence"),
        "active_session": scalar("SELECT max(public_id) FROM sessions WHERE repository_id=? AND status='active'", (rid,)),
        "git": {"available": bool(repo["git_available"]), "branch": repo["git_branch"], "head": repo["git_head"], "dirty": None if repo["git_dirty"] is None else bool(repo["git_dirty"])},
        "database": str(paths(root)[1]),
    }


def operation_status(root: Path, as_json: bool) -> None:
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        data = status_data(root, connection)
    finally:
        connection.close()
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Repository: {data['repository']}\nSessions: {data['sessions']}\nLast capture: {data['last_capture'] or 'never'}")
    print(f"Feedback: {data['feedback']}\nActive decisions: {data['active_decisions']}\nOpen items: {data['open_items']}\nUnconfirmed memories: {data['unconfirmed_memories']}")
    print(f"Active session: {data['active_session'] or 'none'}\nDatabase: {data['database']}")


def words(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9_./-]{2,}", value.lower()) if word not in {"the", "and", "for", "with", "from", "this", "that"}}


def context_records(connection: sqlite3.Connection, rid: int, task: str) -> dict[str, list[dict[str, object]]]:
    selected = {
        "decisions": rows(connection, "decisions", "repository_id=? AND superseded_by_id IS NULL AND status IN ('active','proposed','needs-review')", (rid,), 60),
        "directions": rows(connection, "directions", "repository_id=? AND superseded_by_id IS NULL AND status='active'", (rid,), 60),
        "capabilities": rows(connection, "capabilities", "repository_id=? AND superseded_by_id IS NULL AND status!='deprecated'", (rid,), 60),
        "open_loops": rows(connection, "open_loops", "repository_id=? AND superseded_by_id IS NULL AND status IN ('open','blocked','deferred')", (rid,), 60),
        "tasks": rows(connection, "tasks", "repository_id=? AND superseded_by_id IS NULL AND status IN ('planned','in-progress','blocked','deferred')", (rid,), 40),
        "changes": rows(connection, "changes", "repository_id=? AND superseded_by_id IS NULL", (rid,), 30),
        "feedback": rows(connection, "feedback", "repository_id=? AND type IN ('correction','suggestion','concern','positive')", (rid,), 30),
    }
    query_words = words(task)
    for table, records in selected.items():
        def score(record: dict[str, object]) -> tuple[int, str]:
            text = json.dumps(record).lower()
            relevance = sum(4 for term in query_words if term in text)
            relevance += 3 if record.get("confirmation") in {"human-confirmed", "explicit-human"} else 0
            relevance += 2 if record.get("status") in {"active", "open", "in-progress", "implemented"} else 0
            if table == "feedback":
                relevance += 5 if record.get("type") == "correction" else 3 if record.get("type") == "suggestion" else 1
            return relevance, str(record.get("created_at", ""))
        records.sort(key=score, reverse=True)
        if task:
            relevant = [record for record in records if score(record)[0] >= 4]
            if table == "directions":
                relevant.extend(record for record in records if record not in relevant and record.get("scope") == "repository" and record.get("confirmation") in {"human-confirmed", "explicit-human"})
            if table == "feedback":
                relevant.extend(record for record in records if record not in relevant and record.get("type") in {"correction", "suggestion"})
            selected[table] = relevant[:8]
        else:
            selected[table] = records[:3] if table == "feedback" else records[:5]
    return selected


def render_context(root: Path, task: str, maximum: int) -> str:
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        data = context_records(connection, repo["id"], task)
        recent = rows(connection, "sessions", "repository_id=?", (repo["id"],), 1)
    finally:
        connection.close()
    sections = ["# Memory Hub Context", f"Repository: {repo['name']}"]
    if task:
        sections.append(f"Task: {task}")
    if recent:
        sections.extend(["\n## Current State", recent[0]["summary"]])
    headings = {
        "decisions": "Relevant Decisions", "directions": "Developer Directions",
        "capabilities": "Capabilities", "open_loops": "Open Work", "tasks": "Active Tasks", "changes": "Relevant Files",
        "feedback": "Relevant Feedback",
    }
    for table, heading in headings.items():
        records = data[table]
        if not records:
            continue
        sections.append(f"\n## {heading}")
        for record in records:
            title = record.get("title") or record.get("instruction") or record.get("name") or record.get("path") or record.get("type")
            detail = record.get("summary") or record.get("rationale") or record.get("body") or ""
            if isinstance(detail, list):
                detail = "; ".join(detail)
            label = record.get("status") or record.get("sentiment") or "record"
            sections.append(f"- [{label}] {title}: {detail}".rstrip(": "))
    output = "\n".join(str(part) for part in sections) + "\n"
    if len(output) <= maximum:
        return output
    marker = "\n\n[Context truncated to --max-chars]\n"
    return output[: max(0, maximum - len(marker))].rstrip() + marker


def operation_context(root: Path, task: str, maximum: int) -> None:
    if maximum < 200:
        raise MemoryHubError("--max-chars must be at least 200")
    print(render_context(root, task, maximum), end="")


def record_title(record: dict[str, object]) -> str:
    return str(record.get("title") or record.get("name") or record.get("instruction") or record.get("path") or record.get("summary") or record.get("body") or "")


def search_records(connection: sqlite3.Connection, repository_id: int, query: str, task: str, maximum: int) -> list[dict[str, object]]:
    query_terms = words(query)
    task_terms = words(task)
    if not query_terms or maximum < 1:
        return []
    active = {"active", "open", "in-progress", "implemented", "planned", "proposed", "blocked", "partial"}
    ranked: list[tuple[tuple[object, ...], dict[str, object]]] = []
    normalized_query = " ".join(query.lower().split())
    for table in ("sessions", *ENTITY_TABLES, "feedback"):
        where = "repository_id=?" if table in {"sessions", "feedback"} else "repository_id=? AND superseded_by_id IS NULL"
        for record in rows(connection, table, where, (repository_id,)):
            text = json.dumps(record, ensure_ascii=False).lower()
            title = record_title(record)
            query_overlap = sum(1 for term in query_terms if term in text)
            if not query_overlap:
                continue
            task_overlap = sum(1 for term in task_terms if term in text)
            exact_title = int(" ".join(title.lower().split()) == normalized_query)
            is_active = int(record.get("status") in active)
            human = int(record.get("confirmation") in {"human-confirmed", "explicit-human"})
            feedback_weight = 5 if record.get("type") == "correction" else 3 if record.get("type") == "suggestion" else 1 if table == "feedback" else 0
            score = exact_title * 100 + query_overlap * 12 + task_overlap * 5 + is_active * 3 + human * 2 + feedback_weight
            result = dict(record)
            result["result_type"] = table
            result["title"] = title
            result["score"] = score
            ranked.append(((score, str(record.get("created_at") or ""), table, str(record["id"])), result))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in ranked[:maximum]]


def operation_recall(root: Path, query: str, task: str, maximum: int, as_json: bool) -> None:
    if maximum < 1:
        raise ValidationError("--max-results must be at least 1")
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        results = search_records(connection, repo["id"], query, task, maximum)
    finally:
        connection.close()
    if as_json:
        print(json.dumps({"query": query, "task": task or None, "results": results}, indent=2))
        return
    if not results:
        print("No matching memories.")
        return
    for record in results:
        status = f" [{record['status']}]" if record.get("status") else ""
        print(f"{record['result_type']} {record['id']}{status}: {record['title']}")


def reference_issues(connection: sqlite3.Connection, repository_id: int) -> list[dict[str, str]]:
    known = {row[0] for table in ("sessions", *ENTITY_TABLES) for row in connection.execute(f"SELECT public_id FROM {table} WHERE repository_id=?", (repository_id,))}
    issues: list[dict[str, str]] = []
    for table in ENTITY_TABLES:
        columns = {"supersedes_id", "superseded_by_id", "evidence_ids"} & ({"supersedes_id", "superseded_by_id"} | JSON_COLUMNS.get(table, set()))
        if table == "changes":
            columns.add("task_ids")
        if table == "directions":
            columns.add("correction_of")
        for row in connection.execute(f"SELECT public_id,{','.join(sorted(columns))} FROM {table} WHERE repository_id=?", (repository_id,)):
            for field in columns:
                value = row[field]
                references = []
                if field in {"evidence_ids", "task_ids"}:
                    try:
                        decoded = json.loads(value or "[]")
                        references = decoded if isinstance(decoded, list) else []
                    except (TypeError, json.JSONDecodeError):
                        issues.append({"record": row["public_id"], "field": field, "reference": "<invalid-json>"})
                elif value:
                    references = [value]
                for reference in references:
                    if reference not in known:
                        issues.append({"record": row["public_id"], "field": field, "reference": str(reference)})
    for row in connection.execute("SELECT public_id,from_id,to_id FROM relationships WHERE repository_id=?", (repository_id,)):
        for field in ("from_id", "to_id"):
            if row[field] not in known:
                issues.append({"record": row["public_id"], "field": field, "reference": row[field]})
    for row in connection.execute("SELECT public_id,record_id,session_id FROM feedback WHERE repository_id=?", (repository_id,)):
        if row["record_id"] and row["record_id"] not in known:
            issues.append({"record": row["public_id"], "field": "record_id", "reference": row["record_id"]})
        if row["session_id"] and not connection.execute(
            "SELECT 1 FROM sessions WHERE repository_id=? AND id=?", (repository_id, row["session_id"])
        ).fetchone():
            issues.append({"record": row["public_id"], "field": "session_id", "reference": str(row["session_id"])})
    return issues


def operation_dream(root: Path, apply: bool, as_json: bool) -> None:
    connection = connect(require_initialized(root))
    report: dict[str, object] = {"mode": "apply" if apply else "dry-run"}
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        rid = repo["id"]
        connection.execute("BEGIN IMMEDIATE")
        dangling = reference_issues(connection, rid)
        duplicates: list[dict[str, object]] = []
        repair_candidates: dict[tuple[str, str, str], set[str]] = {}
        status_repairs: list[tuple[str, str]] = []
        for table in ENTITY_TABLES:
            records = rows(connection, table, "repository_id=?", (rid,))
            seen: dict[str, str] = {}
            for record in records:
                canonical = json.dumps({key: value for key, value in record.items() if key not in {"id", "created_at", "session_id", "supersedes_id", "superseded_by_id"}}, sort_keys=True, separators=(",", ":"))
                if canonical in seen:
                    duplicates.append({"type": table, "ids": sorted([seen[canonical], str(record["id"])])})
                else:
                    seen[canonical] = str(record["id"])
                old_id = record.get("supersedes_id")
                new_id = record.get("superseded_by_id")
                if old_id:
                    old = connection.execute(f"SELECT superseded_by_id FROM {table} WHERE repository_id=? AND public_id=?", (rid, old_id)).fetchone()
                    if old and old[0] in {None, record["id"]} and old[0] != record["id"]:
                        repair_candidates.setdefault((table, str(old_id), "superseded_by_id"), set()).add(str(record["id"]))
                if new_id:
                    new = connection.execute(f"SELECT supersedes_id FROM {table} WHERE repository_id=? AND public_id=?", (rid, new_id)).fetchone()
                    if new and new[0] in {None, record["id"]} and new[0] != record["id"]:
                        repair_candidates.setdefault((table, str(new_id), "supersedes_id"), set()).add(str(record["id"]))
                    if new and table in {"decisions", "directions"} and record.get("status") != "superseded":
                        status_repairs.append((table, str(record["id"])))
        seen_feedback: dict[str, str] = {}
        for record in rows(connection, "feedback", "repository_id=?", (rid,)):
            canonical = json.dumps(
                {key: value for key, value in record.items() if key not in {"id", "created_at"}},
                sort_keys=True, separators=(",", ":"),
            )
            if canonical in seen_feedback:
                duplicates.append({"type": "feedback", "ids": sorted([seen_feedback[canonical], str(record["id"])])})
            else:
                seen_feedback[canonical] = str(record["id"])
        reciprocal_repairs = [(*key, next(iter(values))) for key, values in repair_candidates.items() if len(values) == 1]
        fts_count = sum(connection.execute(f"SELECT count(*) FROM {table} WHERE repository_id=?", (rid,)).fetchone()[0] for table in (*ENTITY_TABLES, "feedback"))
        if apply:
            for table, identifier, field, value in reciprocal_repairs:
                connection.execute(f"UPDATE {table} SET {field}=? WHERE repository_id=? AND public_id=?", (value, rid, identifier))
            for table, identifier in status_repairs:
                connection.execute(f"UPDATE {table} SET status='superseded' WHERE repository_id=? AND public_id=?", (rid, identifier))
            try:
                connection.execute("DELETE FROM memory_fts")
                for table in (*ENTITY_TABLES, "feedback"):
                    for record in rows(connection, table, "repository_id=?", (rid,)):
                        fts_add(connection, table, str(record["id"]), record)
            except sqlite3.OperationalError:
                fts_count = 0
            connection.commit()
        else:
            connection.rollback()
        report.update({
            "fts_rebuilt": apply, "fts_records": fts_count, "reciprocal_repairs": len(reciprocal_repairs),
            "status_repairs": len(status_repairs), "dangling_references": dangling,
            "dangling_reference_count": len(dangling), "duplicate_candidates": duplicates,
            "duplicate_candidate_count": len(duplicates),
        })
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Dream {report['mode']}: FTS records={report['fts_records']}, reciprocal repairs={report['reciprocal_repairs']}, status repairs={report['status_repairs']}")
        print(f"Dangling references={report['dangling_reference_count']}, exact duplicate candidates={report['duplicate_candidate_count']}")


def md_escape(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|")


def record_markdown(table: str, record: dict[str, object]) -> str:
    title = record.get("title") or record.get("name") or record.get("instruction") or record.get("path") or record.get("summary") or record.get("body") or record["id"]
    lines = [f"### {md_escape(title)}", "", f"- ID: `{record['id']}`"]
    for field in ("status", "kind", "type", "scope", "sentiment", "rating", "session_id", "record_id", "origin", "importance", "source", "confidence", "confirmation", "created_at"):
        if record.get(field) is not None:
            lines.append(f"- {field.replace('_', ' ').title()}: {md_escape(record[field])}")
    for field in ("summary", "body", "result", "rationale", "alternatives", "tradeoffs", "reconsider_when", "file_paths", "test_paths", "limitations", "next_step"):
        value = record.get(field)
        if value:
            text = "; ".join(value) if isinstance(value, list) else value
            lines.extend(["", f"**{field.replace('_', ' ').title()}:** {md_escape(text)}"])
    return "\n".join(lines) + "\n"


def write_export(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n> Generated from `.memory-hub/memory.db` at {now()}. SQLite remains authoritative.\n\n{body.rstrip()}\n", encoding="utf-8")


def session_export_name(connection: sqlite3.Connection, repository_id: int, session: sqlite3.Row) -> str:
    date = session["started_at"][:10]
    sequence = connection.execute(
        """SELECT count(*) FROM sessions WHERE repository_id=? AND substr(started_at,1,10)=?
           AND (started_at<? OR (started_at=? AND id<=?))""",
        (repository_id, date, session["started_at"], session["started_at"], session["id"]),
    ).fetchone()[0]
    return f"{date}-{sequence:03d}.md"


def session_markdown(connection: sqlite3.Connection, session: sqlite3.Row) -> str:
    decoded = decode_row("sessions", session)
    parts = [f"**Goal:** {decoded['goal']}\n\n**Outcome:** {decoded['outcome']}\n\n{decoded['summary']}"]
    for table in ENTITY_TABLES:
        records = rows(connection, table, "session_id=?", (session["id"],))
        if records:
            parts.append(f"## {table.replace('_', ' ').title()}\n\n" + "\n".join(record_markdown(table, item) for item in records))
    feedback = rows(connection, "feedback", "session_id=?", (session["id"],))
    if feedback:
        parts.append("## Feedback\n\n" + "\n".join(record_markdown("feedback", item) for item in feedback))
    relationships = rows(connection, "relationships", "session_id=?", (session["id"],))
    if relationships:
        lines = [f"- `{item['from_id']}` {item['type']} `{item['to_id']}`" for item in relationships]
        parts.append("## Relationships\n\n" + "\n".join(lines))
    return "\n\n".join(parts)


def operation_export(root: Path, target: str, session_identifier: str | None) -> None:
    connection = connect(require_initialized(root))
    output = paths(root)[0] / "exports"
    generated: list[Path] = []
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        rid = repo["id"]
        if target == "decisions":
            path = output / "decisions.md"
            records = rows(connection, "decisions", "repository_id=?", (rid,))
            write_export(path, "Decisions", "\n".join(record_markdown("decisions", item) for item in records) or "No decisions recorded.")
            generated.append(path)
        elif target == "session":
            session = connection.execute(
                "SELECT * FROM sessions WHERE repository_id=? AND (public_id=? OR CAST(id AS TEXT)=?)",
                (rid, session_identifier, session_identifier),
            ).fetchone()
            if session is None:
                raise MemoryHubError(f"session not found: {session_identifier}")
            decoded = decode_row("sessions", session)
            path = output / "sessions" / session_export_name(connection, rid, session)
            write_export(path, f"Session {decoded['id']}", session_markdown(connection, session))
            generated.append(path)
        else:
            mappings = [
                ("decisions", "Decisions", "decisions.md"), ("directions", "Developer Directions", "developer-directions.md"),
                ("capabilities", "Capabilities", "capabilities.md"), ("open_loops", "Open Work", "open-work.md"),
                ("feedback", "Feedback", "feedback.md"),
            ]
            for table, title, filename in mappings:
                records = rows(connection, table, "repository_id=?", (rid,))
                path = output / filename
                write_export(path, title, "\n".join(record_markdown(table, item) for item in records) or f"No {title.lower()} recorded.")
                generated.append(path)
            state = status_data(root, connection)
            state_body = "\n".join(f"- {key.replace('_', ' ').title()}: {md_escape(value)}" for key, value in state.items() if key != "git")
            state_path = output / "repository-state.md"
            write_export(state_path, "Repository State", state_body)
            generated.append(state_path)
            sessions = connection.execute("SELECT * FROM sessions WHERE repository_id=? ORDER BY started_at", (rid,)).fetchall()
            for session in sessions:
                decoded = decode_row("sessions", session)
                path = output / "sessions" / session_export_name(connection, rid, session)
                write_export(path, f"Session {decoded['id']}", session_markdown(connection, session))
                generated.append(path)
            readme = output / "README.md"
            links = "\n".join(f"- [{path.relative_to(output)}]({path.relative_to(output).as_posix()})" for path in generated)
            write_export(readme, f"Memory Hub: {repo['name']}", links or "No exports generated.")
            generated.insert(0, readme)
    finally:
        connection.close()
    print("Generated exports:\n" + "\n".join(str(path) for path in generated))


def record_endpoint(endpoint: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"/api/records/([^/]+)/([^/]+)", endpoint)
    if not match:
        return None
    table = TYPE_ALIASES.get(match.group(1).lower())
    if table is None:
        raise NotFoundError("unsupported record type")
    return table, match.group(2)


def get_record(connection: sqlite3.Connection, repository_id: int, table: str, identifier: str) -> dict[str, object]:
    row = connection.execute(f"SELECT * FROM {table} WHERE repository_id=? AND public_id=?", (repository_id, identifier)).fetchone()
    if row is None:
        raise NotFoundError(f"{table} record not found: {identifier}")
    return decode_feedback(connection, row) if table == "feedback" else decode_row(table, row)


def api_patch_record(root: Path, endpoint: str, payload: object) -> dict[str, object]:
    target = record_endpoint(endpoint)
    if target is None:
        raise NotFoundError("API endpoint not found")
    table, identifier = target
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        current = get_record(connection, repo["id"], table, identifier)
        patch = validate_feedback_patch(payload) if table == "feedback" else validate_record_patch(connection, repo["id"], table, current, payload)
        updates: dict[str, object] = {}
        for field, value in patch.items():
            column = "supersedes_id" if field == "supersedes" else field
            updates[column] = json_text(value) if column in JSON_COLUMNS.get(table, set()) else value
        connection.execute("BEGIN IMMEDIATE")
        if table == "feedback":
            assignments = ",".join(f"{field}=?" for field in updates)
            connection.execute(
                f"UPDATE feedback SET {assignments} WHERE repository_id=? AND public_id=?",
                (*updates.values(), repo["id"], identifier),
            )
            updated = get_record(connection, repo["id"], table, identifier)
            fts_replace(connection, table, identifier, updated)
            connection.commit()
            return updated
        old_supersedes = current.get("supersedes_id")
        new_supersedes = patch.get("supersedes", old_supersedes)
        if "supersedes" in patch and new_supersedes != old_supersedes:
            if old_supersedes:
                connection.execute(
                    f"UPDATE {table} SET superseded_by_id=NULL WHERE repository_id=? AND public_id=? AND superseded_by_id=?",
                    (repo["id"], old_supersedes, identifier),
                )
            if new_supersedes:
                old = connection.execute(f"SELECT superseded_by_id FROM {table} WHERE repository_id=? AND public_id=?", (repo["id"], new_supersedes)).fetchone()
                if old is None:
                    raise ValidationError(f"supersedes: unknown stable ID '{new_supersedes}'")
                if old[0] not in {None, identifier}:
                    raise ConflictError(f"record {new_supersedes} is already superseded by {old[0]}")
                connection.execute(f"UPDATE {table} SET superseded_by_id=? WHERE repository_id=? AND public_id=?", (identifier, repo["id"], new_supersedes))
                if table in {"decisions", "directions"}:
                    connection.execute(f"UPDATE {table} SET status='superseded' WHERE repository_id=? AND public_id=?", (repo["id"], new_supersedes))
        assignments = ",".join(f"{field}=?" for field in updates)
        connection.execute(f"UPDATE {table} SET {assignments} WHERE repository_id=? AND public_id=?", (*updates.values(), repo["id"], identifier))
        updated = get_record(connection, repo["id"], table, identifier)
        fts_replace(connection, table, identifier, updated)
        connection.commit()
        return updated
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def api_delete_record(root: Path, endpoint: str) -> None:
    target = record_endpoint(endpoint)
    if target is None:
        raise NotFoundError("API endpoint not found")
    table, identifier = target
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        connection.execute("BEGIN IMMEDIATE")
        get_record(connection, repo["id"], table, identifier)
        references: list[str] = []
        if connection.execute("SELECT 1 FROM relationships WHERE repository_id=? AND (from_id=? OR to_id=?)", (repo["id"], identifier, identifier)).fetchone():
            references.append("relationships")
        if table != "feedback" and connection.execute(
            "SELECT 1 FROM feedback WHERE repository_id=? AND record_id=?", (repo["id"], identifier)
        ).fetchone():
            references.append("feedback")
        for other in ("sessions", *ENTITY_TABLES, "relationships"):
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({other})") if row[2].upper() == "TEXT" and row[1] not in {"public_id"}]
            clause = " OR ".join(f"instr({field},?)>0" for field in columns)
            if clause and connection.execute(f"SELECT 1 FROM {other} WHERE repository_id=? AND ({clause})", (repo["id"], *([identifier] * len(columns)))).fetchone():
                references.append(other)
        if references:
            raise ConflictError(f"record is referenced by: {', '.join(sorted(set(references)))}")
        connection.execute(f"DELETE FROM {table} WHERE repository_id=? AND public_id=?", (repo["id"], identifier))
        try:
            connection.execute("DELETE FROM memory_fts WHERE memory_type=? AND public_id=?", (table, identifier))
        except sqlite3.OperationalError:
            pass
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def api_data(root: Path, endpoint: str, query: dict[str, list[str]]) -> object:
    connection = connect(require_initialized(root))
    try:
        migrate(connection)
        repo = repository_row(connection, root)
        rid = repo["id"]
        session_match = re.fullmatch(r"/api/sessions/([^/]+)", endpoint)
        if session_match:
            session = connection.execute("SELECT * FROM sessions WHERE repository_id=? AND public_id=?", (rid, session_match.group(1))).fetchone()
            if session is None:
                raise NotFoundError(f"session not found: {session_match.group(1)}")
            result: dict[str, object] = {"session": decode_row("sessions", session)}
            for table in ENTITY_TABLES:
                result[table] = rows(connection, table, "repository_id=? AND session_id=?", (rid, session["id"]))
            result["relationships"] = rows(connection, "relationships", "repository_id=? AND session_id=?", (rid, session["id"]))
            result["feedback"] = rows(connection, "feedback", "repository_id=? AND session_id=?", (rid, session["id"]))
            return result
        target = record_endpoint(endpoint)
        if target:
            record = get_record(connection, rid, *target)
            record["editable_fields"] = sorted(EDITABLE_FIELDS[target[0]])
            return record
        if endpoint == "/api/overview":
            status = status_data(root, connection)
            recent_sessions = rows(connection, "sessions", "repository_id=?", (rid,), 1)
            return {
                "repository": {"name": repo["name"], "path": repo["root_path"], "branch": repo["git_branch"], "state": recent_sessions[0]["summary"] if recent_sessions else "No sessions captured yet."},
                "last_capture": status["last_capture"],
                "counts": {"sessions": status["sessions"], "feedback": status["feedback"], "active_decisions": status["active_decisions"], "open_work": status["open_items"], "capabilities": connection.execute("SELECT count(*) FROM capabilities WHERE repository_id=?", (rid,)).fetchone()[0]},
                "recent_decisions": rows(connection, "decisions", "repository_id=?", (rid,), 4),
                "open_work": rows(connection, "open_loops", "repository_id=? AND status IN ('open','blocked','deferred')", (rid,), 4),
                "recent_sessions": recent_sessions,
                "capabilities": rows(connection, "capabilities", "repository_id=?", (rid,), 4),
            }
        if endpoint == "/api/decisions":
            return {"decisions": rows(connection, "decisions", "repository_id=?", (rid,))}
        if endpoint == "/api/capabilities":
            return {"capabilities": rows(connection, "capabilities", "repository_id=?", (rid,))}
        if endpoint == "/api/directions":
            return {"directions": rows(connection, "directions", "repository_id=?", (rid,))}
        if endpoint == "/api/open-work":
            open_records = rows(connection, "open_loops", "repository_id=? AND status!='resolved'", (rid,))
            tasks = rows(connection, "tasks", "repository_id=? AND status NOT IN ('completed','abandoned')", (rid,))
            return {"open_work": open_records + tasks}
        if endpoint == "/api/sessions":
            return {"sessions": rows(connection, "sessions", "repository_id=?", (rid,))}
        if endpoint == "/api/feedback":
            clauses = ["feedback.repository_id=?"]
            params: list[object] = [rid]
            allowed_query = {"session_id", "record_id"}
            unknown_query = set(query) - allowed_query
            if unknown_query:
                fail(next(iter(sorted(unknown_query))), "unknown feedback query filter")
            if "session_id" in query:
                value = query["session_id"][0].strip()
                if not value:
                    fail("session_id", "query filter must be a non-empty session ID")
                clauses.append("feedback.session_id=(SELECT id FROM sessions WHERE repository_id=? AND public_id=?)")
                params.extend((rid, value))
            if "record_id" in query:
                value = query["record_id"][0].strip()
                if not value:
                    fail("record_id", "query filter must be a non-empty record ID")
                clauses.append("feedback.record_id=?")
                params.append(value)
            return {"feedback": rows(connection, "feedback", " AND ".join(clauses), tuple(params))}
        if endpoint == "/api/timeline":
            events: list[dict[str, object]] = []
            for table in ("sessions", "checkpoints", "changes", "decisions", "tasks", "feedback"):
                for record in rows(connection, table, "repository_id=?", (rid,), 100):
                    record["event_type"] = table[:-1] if table.endswith("s") else table
                    if table != "feedback":
                        record["type"] = record["event_type"]
                    events.append(record)
            return {"timeline": events}
        if endpoint == "/api/search":
            term = (query.get("q") or [""])[0].strip()
            task = (query.get("task") or [""])[0].strip()
            return {"results": search_records(connection, rid, term, task, 10)}
        raise NotFoundError("API endpoint not found")
    finally:
        connection.close()


class MemoryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], root: Path, token: str):
        super().__init__(address, handler)
        self.repo_root = root
        self.token = token


class Handler(BaseHTTPRequestHandler):
    server: MemoryServer

    def log_message(self, format_string: str, *args: object) -> None:
        return

    def send_json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_api_error(self, exc: Exception) -> None:
        if isinstance(exc, ValidationError):
            status = 400
        elif isinstance(exc, NotFoundError):
            status = 404
        elif isinstance(exc, (ConflictError, sqlite3.IntegrityError)):
            status = 409
        elif isinstance(exc, PayloadTooLargeError):
            status = 413
        else:
            status = 500
        message = str(exc) if status != 500 else "internal server error"
        self.send_json({"error": message}, status)

    def read_json(self) -> object:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValidationError("Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValidationError("invalid Content-Length") from exc
        if length < 0:
            raise ValidationError("invalid Content-Length")
        if length > MAX_JSON_BODY:
            raise PayloadTooLargeError("JSON body exceeds 1 MiB limit")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid JSON body: {exc}") from exc

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "ok", "token": self.server.token, "pid": os.getpid()})
            return
        if parsed.path.startswith("/api/"):
            try:
                self.send_json(api_data(self.server.repo_root, parsed.path, parse_qs(parsed.query, keep_blank_values=True)))
            except Exception as exc:
                self.send_api_error(exc)
            return
        relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
        assets = Path(__file__).resolve().parent.parent / "assets" / "web"
        requested = (assets / relative).resolve()
        try:
            requested.relative_to(assets.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not requested.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = requested.read_bytes()
        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/feedback":
            try:
                payload = self.read_json()
                self.send_json(create_feedback(self.server.repo_root, payload), 201)
            except Exception as exc:
                self.send_api_error(exc)
            return
        if parsed.path != "/api/shutdown" or self.headers.get("X-Memory-Hub-Token") != self.server.token:
            self.send_json({"error": "not found"}, 404)
            return
        self.send_json({"status": "stopping"})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            self.send_json(api_patch_record(self.server.repo_root, parsed.path, payload))
        except Exception as exc:
            self.send_api_error(exc)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            api_delete_record(self.server.repo_root, parsed.path)
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except Exception as exc:
            self.send_api_error(exc)


def health(port: int, token: str | None = None, timeout: float = 0.5) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            data = json.loads(response.read())
        if data.get("status") == "ok" and (token is None or secrets.compare_digest(str(data.get("token", "")), token)):
            return data
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def read_server_state(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and type(value.get("port")) is int and type(value.get("pid")) is int and isinstance(value.get("token"), str):
            return value
    except (OSError, ValueError):
        pass
    return None


def foreground_serve(root: Path, port: int, token: str) -> None:
    server_path = paths(root)[3]
    server = MemoryServer(("127.0.0.1", port), Handler, root, token)
    actual_port = server.server_address[1]
    atomic_json(server_path, {"pid": os.getpid(), "port": actual_port, "token": token, "started_at": now(), "repo_root": str(root)})
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        state = read_server_state(server_path)
        if state and state.get("pid") == os.getpid() and state.get("token") == token:
            try:
                server_path.unlink()
            except OSError:
                pass


def operation_server(root: Path) -> None:
    require_initialized(root)
    server_path = paths(root)[3]
    lock_path = paths(root)[0] / "server.lock"
    deadline = time.monotonic() + 10
    while True:
        try:
            lock_path.mkdir()
            break
        except FileExistsError:
            state = read_server_state(server_path)
            if state and health(state["port"], state["token"]):
                print(f"Memory Hub is available at http://127.0.0.1:{state['port']}")
                return
            if time.monotonic() >= deadline:
                raise MemoryHubError("timed out waiting for another server start")
            time.sleep(0.1)
    try:
        state = read_server_state(server_path)
        if state and health(state["port"], state["token"]):
            print(f"Memory Hub is available at http://127.0.0.1:{state['port']}")
            return
        if state:
            try:
                server_path.unlink()
            except OSError:
                pass
        token = secrets.token_urlsafe(32)
        command = [sys.executable, str(Path(__file__).resolve()), "_serve", "--repo-root", str(root), "--port", "0", "--token", token]
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        except OSError as exc:
            raise MemoryHubError(f"could not start server: {exc}") from exc
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = read_server_state(server_path)
            if state and state.get("token") == token and health(state["port"], token):
                print(f"Memory Hub is available at http://127.0.0.1:{state['port']}")
                return
            time.sleep(0.1)
        raise MemoryHubError("server did not become healthy within 8 seconds")
    finally:
        try:
            lock_path.rmdir()
        except OSError:
            pass


def operation_stop(root: Path) -> None:
    server_path = paths(root)[3]
    state = read_server_state(server_path)
    if not state:
        if server_path.exists():
            server_path.unlink()
        print("Memory Hub server is not running")
        return
    checked = health(state["port"], state["token"])
    if not checked or checked.get("pid") != state["pid"]:
        try:
            server_path.unlink()
        except OSError:
            pass
        raise MemoryHubError("server state was stale or failed token/PID verification; no process was stopped")
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}/api/shutdown", method="POST",
        headers={"X-Memory-Hub-Token": state["token"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            if response.status != 200:
                raise MemoryHubError("verified server refused shutdown")
    except urllib.error.URLError as exc:
        raise MemoryHubError(f"verified server shutdown failed: {exc}") from exc
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and health(state["port"], state["token"], 0.2):
        time.sleep(0.1)
    if health(state["port"], state["token"], 0.2):
        raise MemoryHubError("server did not stop within 5 seconds")
    try:
        server_path.unlink()
    except FileNotFoundError:
        pass
    print("Memory Hub server stopped")


def parser() -> argparse.ArgumentParser:
    root_parser = argparse.ArgumentParser(description="Memory Hub local runtime")
    subparsers = root_parser.add_subparsers(dest="operation", required=True)
    for operation in ("init", "status", "server", "serve", "stop"):
        command = subparsers.add_parser(operation)
        command.add_argument("--repo-root")
        if operation == "status":
            command.add_argument("--json", action="store_true")
    capture = subparsers.add_parser("capture")
    capture.add_argument("--repo-root")
    capture.add_argument("--input", required=True, type=Path)
    feedback = subparsers.add_parser("feedback")
    feedback.add_argument("--repo-root")
    feedback.add_argument("--input", required=True, type=Path)
    context = subparsers.add_parser("context")
    context.add_argument("--repo-root")
    context.add_argument("--task", default="")
    context.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    recall = subparsers.add_parser("recall")
    recall.add_argument("--repo-root")
    recall.add_argument("query", nargs="+")
    recall.add_argument("--task", default="")
    recall.add_argument("--max-results", type=int, default=10)
    recall.add_argument("--json", action="store_true")
    dream = subparsers.add_parser("dream")
    dream.add_argument("--repo-root")
    dream.add_argument("--apply", action="store_true")
    dream.add_argument("--json", action="store_true")
    export = subparsers.add_parser("export")
    export.add_argument("--repo-root")
    export.add_argument("target", nargs="?", choices=("all", "decisions", "session"), default="all")
    export.add_argument("session_id", nargs="?")
    hidden = subparsers.add_parser("_serve", help=argparse.SUPPRESS)
    hidden.add_argument("--repo-root", required=True)
    hidden.add_argument("--port", required=True, type=int)
    hidden.add_argument("--token", required=True)
    return root_parser


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        root = discover_repo(arguments.repo_root)
        operation = arguments.operation
        if operation == "init":
            operation_init(root)
        elif operation == "capture":
            operation_capture(root, arguments.input.expanduser().resolve())
        elif operation == "feedback":
            operation_feedback(root, arguments.input.expanduser().resolve())
        elif operation == "context":
            operation_context(root, arguments.task, arguments.max_chars)
        elif operation == "recall":
            operation_recall(root, " ".join(arguments.query), arguments.task, arguments.max_results, arguments.json)
        elif operation == "dream":
            operation_dream(root, arguments.apply, arguments.json)
        elif operation == "status":
            operation_status(root, arguments.json)
        elif operation == "export":
            if arguments.target == "session" and not arguments.session_id:
                raise MemoryHubError("export session requires a session ID")
            if arguments.target != "session" and arguments.session_id:
                raise MemoryHubError("unexpected session ID")
            operation_export(root, arguments.target, arguments.session_id)
        elif operation in {"server", "serve"}:
            operation_server(root)
        elif operation == "stop":
            operation_stop(root)
        elif operation == "_serve":
            foreground_serve(root, arguments.port, arguments.token)
        return 0
    except (MemoryHubError, sqlite3.Error) as exc:
        print(f"memory-hub {getattr(arguments, 'operation', 'operation')}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("memory-hub: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
