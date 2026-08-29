import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "skills" / "memory-hub" / "scripts" / "memory_hub.py"
ENTITY_ARRAYS = (
    "checkpoints",
    "tasks",
    "changes",
    "decisions",
    "directions",
    "capabilities",
    "open_loops",
    "evidence",
    "relationships",
)


def capture_payload(mode="checkpoint", summary="Work is in progress"):
    payload = {
        "schema_version": 1,
        "session": {
            "mode": mode,
            "agent": "unittest",
            "model": "stdlib",
            "goal": "Exercise Memory Hub",
            "outcome": "partial" if mode == "checkpoint" else "completed",
            "summary": summary,
        },
    }
    payload.update({name: [] for name in ENTITY_ARRAYS})
    return payload


class MemoryHubCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "plain-repository"
        self.repo.mkdir()
        self.capture_number = 0
        self.server_state = None
        self.addCleanup(self.cleanup_server)
        result = self.run_cli("init")
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_cli(self, *arguments, timeout=15):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments, "--repo-root", str(self.repo)],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def capture(self, payload, timeout=15):
        self.capture_number += 1
        path = self.repo / f"capture-{self.capture_number}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return self.run_cli("capture", "--input", str(path), timeout=timeout)

    def status(self):
        result = self.run_cli("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def database_counts(self):
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            tables = ("sessions",) + ENTITY_ARRAYS
            return {
                table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in tables
            }

    def record_id(self, table, field, value):
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                f"SELECT public_id FROM {table} WHERE {field}=?", (value,)
            ).fetchone()
        self.assertIsNotNone(row, f"missing {table} record where {field}={value!r}")
        return row[0]

    def start_server(self):
        if self.server_state and self.server_health(self.server_state):
            return self.server_state
        result = self.run_cli("server", timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)
        server_path = self.repo / ".memory-hub" / "server.json"
        self.server_state = json.loads(server_path.read_text(encoding="utf-8"))
        self.assertTrue(self.server_health(self.server_state))
        return self.server_state

    def cleanup_server(self):
        state = self.server_state
        if not state:
            return
        try:
            self.run_cli("stop", timeout=8)
        except subprocess.TimeoutExpired:
            pass
        if self.server_health(state):
            try:
                os.kill(state["pid"], signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and self.server_health(state):
                time.sleep(0.05)
            if self.server_health(state):
                try:
                    os.kill(state["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        self.server_state = None

    def api_request(self, path, method="GET", body=None, expected_status=200):
        state = self.start_server()
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(
            f"http://127.0.0.1:{state['port']}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as error:
            try:
                status = error.code
                raw = error.read()
            finally:
                error.close()
        payload = json.loads(raw.decode("utf-8")) if raw else None
        self.assertEqual(status, expected_status, payload)
        return payload

    def test_init_is_idempotent_and_supports_non_git_directory(self):
        config_path = self.repo / ".memory-hub" / "config.json"
        first_config = json.loads(config_path.read_text(encoding="utf-8"))

        result = self.run_cli("init")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Git metadata unavailable (non-Git directory)", result.stdout)
        second_config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(second_config["created_at"], first_config["created_at"])
        self.assertEqual(second_config["repository_root"], str(self.repo))
        self.assertEqual(self.status()["sessions"], 0)

    def test_checkpoint_then_close_reuses_the_active_session(self):
        checkpoint = capture_payload(summary="Checkpoint one")
        checkpoint["checkpoints"] = [{"summary": "Checkpoint one", "open_context": "Continue tests"}]
        first = self.capture(checkpoint)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_session = first.stdout.split("Captured session ", 1)[1].split(" ", 1)[0]

        close = self.capture(capture_payload("close", "All tests complete"))

        self.assertEqual(close.returncode, 0, close.stderr)
        closed_session = close.stdout.split("Captured session ", 1)[1].split(" ", 1)[0]
        self.assertEqual(closed_session, first_session)
        state = self.status()
        self.assertEqual(state["sessions"], 1)
        self.assertIsNone(state["active_session"])
        self.assertEqual(self.database_counts()["checkpoints"], 1)

    def test_close_without_active_session_creates_closed_session(self):
        result = self.capture(capture_payload("close", "Nothing to close"))

        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.status()
        self.assertEqual(state["sessions"], 1)
        self.assertIsNone(state["active_session"])
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            status, closed_at = connection.execute(
                "SELECT status, closed_at FROM sessions"
            ).fetchone()
        self.assertEqual(status, "closed")
        self.assertIsNotNone(closed_at)

    def test_strict_malformed_capture_is_transaction_safe(self):
        valid = capture_payload()
        valid["tasks"] = [{
            "title": "Existing task", "status": "planned", "summary": "Must survive rejection"
        }]
        accepted = self.capture(valid)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        before = self.database_counts()

        malformed = capture_payload(summary="Must not update the active session")
        malformed["tasks"] = [{
            "title": "Invalid task", "status": "invented", "summary": "Must not persist",
            "unknown": "strict validation",
        }]
        rejected = self.capture(malformed)

        self.assertEqual(rejected.returncode, 2, rejected.stdout)
        self.assertIn("tasks[0].unknown: unknown field", rejected.stderr)
        self.assertEqual(self.database_counts(), before)
        self.assertNotEqual(self.status()["last_capture"], None)

    def test_secret_is_rejected_before_any_persistence(self):
        payload = capture_payload(summary="api_key=supersecretcredentialvalue")

        result = self.capture(payload)

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("suspected credential assignment", result.stderr)
        self.assertIn("before persistence", result.stderr)
        self.assertEqual(self.database_counts()["sessions"], 0)

    def test_authority_and_required_evidence_are_validated(self):
        cases = [
            ({"title": "No reason", "status": "active", "scope": "tests", "rationale": []}, "expected at least one rationale"),
            ({"title": "Wrong authority", "status": "active", "scope": "tests", "rationale": ["Reason"], "confirmation": "human-confirmed"}, "requires source 'human'"),
        ]
        for decision, message in cases:
            with self.subTest(message=message):
                payload = capture_payload()
                payload["decisions"] = [decision]
                result = self.capture(payload)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(message, result.stderr)
        payload = capture_payload()
        payload["capabilities"] = [{"name": "Unsupported", "status": "implemented", "summary": "No evidence"}]
        result = self.capture(payload)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("implemented requires", result.stderr)
        self.assertEqual(self.database_counts()["sessions"], 0)

    def test_absolute_and_traversing_paths_are_rejected(self):
        for unsafe_path in ("../outside.txt", "/etc/passwd", "folder/../../outside.txt"):
            with self.subTest(path=unsafe_path):
                payload = capture_payload()
                payload["changes"] = [{
                    "path": unsafe_path, "kind": "modified", "summary": "Unsafe path"
                }]
                result = self.capture(payload)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("expected a safe repository-relative path", result.stderr)
        self.assertEqual(self.database_counts()["sessions"], 0)

    def test_status_json_reports_counts_and_active_session(self):
        payload = capture_payload(summary="Status summary")
        payload["decisions"] = [{
            "title": "Use unittest", "status": "active", "scope": "tests",
            "rationale": ["It is in the standard library"],
            "source": "agent", "confirmation": "agent-inferred",
        }]
        payload["open_loops"] = [{
            "title": "Finish coverage", "kind": "unfinished-work", "status": "open",
            "summary": "More scenarios remain",
        }]
        result = self.capture(payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        state = self.status()

        self.assertEqual(state["repository"], self.repo.name)
        self.assertEqual(state["repository_root"], str(self.repo))
        self.assertEqual(state["sessions"], 1)
        self.assertEqual(state["active_decisions"], 1)
        self.assertEqual(state["open_items"], 1)
        self.assertTrue(state["active_session"].startswith("ses_"))
        self.assertFalse(state["git"]["available"])

    def test_context_is_task_focused_and_bounded(self):
        payload = capture_payload(summary="Several work items are tracked")
        payload["tasks"] = [
            {"title": "Repair lunar parser", "status": "in-progress", "summary": "Handle lunar tokens"},
            {"title": "Polish docs", "status": "planned", "summary": "Update prose"},
        ]
        payload["directions"] = [{
            "instruction": "Keep lunar parsing deterministic", "status": "active",
            "scope": "lunar parser", "origin": "human", "importance": "high",
        }]
        self.assertEqual(self.capture(payload).returncode, 0)

        result = self.run_cli("context", "--task", "lunar parser", "--max-chars", "220")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout), 220)
        self.assertIn("Task: lunar parser", result.stdout)
        self.assertIn("Context truncated to --max-chars", result.stdout)

    def test_recall_is_task_aware_bounded_and_excludes_superseded_records(self):
        initial = capture_payload(summary="Ranking fixtures")
        initial["decisions"] = [
            {
                "title": "Sharedneedle lunar choice",
                "status": "active",
                "scope": "lunar parser",
                "rationale": ["Relevant to lunar work"],
            },
            {
                "title": "Sharedneedle documentation choice",
                "status": "active",
                "scope": "documentation",
                "rationale": ["Relevant to prose work"],
            },
            {
                "title": "Obsolete uniquearchive choice",
                "status": "active",
                "scope": "archive",
                "rationale": ["This will be replaced"],
            },
        ]
        accepted = self.capture(initial)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        obsolete_id = self.record_id("decisions", "title", "Obsolete uniquearchive choice")

        replacement = capture_payload(summary="Replacement fixture")
        replacement["decisions"] = [{
            "title": "Current archive choice",
            "status": "active",
            "scope": "archive",
            "rationale": ["Newer evidence"],
            "supersedes": obsolete_id,
        }]
        accepted = self.capture(replacement)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        ranked = self.run_cli(
            "recall", "sharedneedle", "--task", "lunar parser",
            "--max-results", "2", "--json",
        )
        self.assertEqual(ranked.returncode, 0, ranked.stderr)
        results = json.loads(ranked.stdout)["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Sharedneedle lunar choice")

        superseded = self.run_cli("recall", "uniquearchive", "--json")
        self.assertEqual(superseded.returncode, 0, superseded.stderr)
        self.assertEqual(json.loads(superseded.stdout)["results"], [])

        invalid_bound = self.run_cli("recall", "sharedneedle", "--max-results", "0")
        self.assertEqual(invalid_bound.returncode, 2)
        self.assertIn("--max-results must be at least 1", invalid_bound.stderr)

    def test_dream_dry_run_does_not_write_and_apply_rebuilds_idempotently(self):
        initial = capture_payload(summary="Dream fixtures")
        initial["decisions"] = [{
            "title": "Old searchable nebula",
            "status": "active",
            "scope": "dreaming",
            "rationale": ["Original"],
        }]
        self.assertEqual(self.capture(initial).returncode, 0)
        old_id = self.record_id("decisions", "title", "Old searchable nebula")
        replacement = capture_payload(summary="Dream replacement")
        replacement["decisions"] = [{
            "title": "New searchable nebula",
            "status": "active",
            "scope": "dreaming",
            "rationale": ["Replacement"],
            "supersedes": old_id,
        }]
        self.assertEqual(self.capture(replacement).returncode, 0)
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE decisions SET superseded_by_id=NULL WHERE public_id=?", (old_id,)
            )
            connection.execute("DELETE FROM memory_fts")
            connection.commit()

        dry_run = self.run_cli("dream", "--json")
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        dry_report = json.loads(dry_run.stdout)
        self.assertEqual(dry_report["mode"], "dry-run")
        self.assertFalse(dry_report["fts_rebuilt"])
        self.assertEqual(dry_report["reciprocal_repairs"], 1)
        with sqlite3.connect(database) as connection:
            self.assertIsNone(connection.execute(
                "SELECT superseded_by_id FROM decisions WHERE public_id=?", (old_id,)
            ).fetchone()[0])
            self.assertEqual(connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0], 0)

        applied = self.run_cli("dream", "--apply", "--json")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        applied_report = json.loads(applied.stdout)
        self.assertTrue(applied_report["fts_rebuilt"])
        self.assertEqual(applied_report["reciprocal_repairs"], 1)
        with sqlite3.connect(database) as connection:
            repaired = connection.execute(
                "SELECT superseded_by_id FROM decisions WHERE public_id=?", (old_id,)
            ).fetchone()[0]
            indexed = connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0]
        self.assertIsNotNone(repaired)
        self.assertEqual(indexed, applied_report["fts_records"])

        repeated = self.run_cli("dream", "--apply", "--json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_report = json.loads(repeated.stdout)
        self.assertEqual(repeated_report["reciprocal_repairs"], 0)
        self.assertEqual(repeated_report["status_repairs"], 0)
        self.assertEqual(repeated_report["fts_records"], indexed)
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0], indexed)

    def test_full_and_targeted_exports(self):
        payload = capture_payload(summary="Exportable state")
        payload["tasks"] = [{"title": "Unique exported task", "status": "completed", "summary": "Included in session details"}]
        payload["decisions"] = [{
            "title": "Export Markdown", "status": "active", "scope": "exports",
            "rationale": ["Humans can inspect it"],
        }]
        captured = self.capture(payload)
        self.assertEqual(captured.returncode, 0, captured.stderr)
        session_id = captured.stdout.split("Captured session ", 1)[1].split(" ", 1)[0]

        decisions = self.run_cli("export", "decisions")
        self.assertEqual(decisions.returncode, 0, decisions.stderr)
        decisions_path = self.repo / ".memory-hub" / "exports" / "decisions.md"
        self.assertIn("Export Markdown", decisions_path.read_text(encoding="utf-8"))

        session = self.run_cli("export", "session", session_id)
        self.assertEqual(session.returncode, 0, session.stderr)
        session_files = list((self.repo / ".memory-hub" / "exports" / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        self.assertIn(session_id, session_files[0].read_text(encoding="utf-8"))

        full = self.run_cli("export", "all")
        self.assertEqual(full.returncode, 0, full.stderr)
        exports = self.repo / ".memory-hub" / "exports"
        expected = {"README.md", "decisions.md", "developer-directions.md", "capabilities.md", "open-work.md", "repository-state.md"}
        self.assertTrue(expected.issubset({path.name for path in exports.iterdir()}))
        self.assertIn("Unique exported task", session_files[0].read_text(encoding="utf-8"))

    def test_stable_id_can_be_superseded_across_captures(self):
        initial = capture_payload(summary="Initial decision")
        initial["decisions"] = [{
            "title": "Original choice", "status": "active", "scope": "storage",
            "rationale": ["Initial evidence"],
        }]
        self.assertEqual(self.capture(initial).returncode, 0)
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            stable_id = connection.execute("SELECT public_id FROM decisions").fetchone()[0]

        replacement = capture_payload(summary="Decision revised")
        replacement["decisions"] = [{
            "title": "Replacement choice", "status": "active", "scope": "storage",
            "rationale": ["Better evidence"], "supersedes": stable_id,
        }]
        result = self.capture(replacement)

        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(database) as connection:
            old = connection.execute(
                "SELECT status, superseded_by_id FROM decisions WHERE public_id=?", (stable_id,)
            ).fetchone()
            new = connection.execute(
                "SELECT public_id, supersedes_id FROM decisions WHERE title='Replacement choice'"
            ).fetchone()
        self.assertEqual(old, ("superseded", new[0]))
        self.assertEqual(new[1], stable_id)

    def test_forward_local_supersession_is_order_independent(self):
        payload = capture_payload()
        payload["decisions"] = [
            {"id": "new", "title": "New", "status": "active", "scope": "storage", "rationale": ["Better"], "supersedes": "old"},
            {"id": "old", "title": "Old", "status": "active", "scope": "storage", "rationale": ["Earlier"]},
        ]
        result = self.capture(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            old_status, old_replacement = connection.execute(
                "SELECT status, superseded_by_id FROM decisions WHERE title='Old'"
            ).fetchone()
            new_id = connection.execute("SELECT public_id FROM decisions WHERE title='New'").fetchone()[0]
        self.assertEqual((old_status, old_replacement), ("superseded", new_id))

    def test_git_change_path_and_kind_are_verified(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        tracked = self.repo / "tracked.txt"
        tracked.write_text("first\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"],
            check=True,
        )
        tracked.write_text("second\n", encoding="utf-8")
        payload = capture_payload()
        payload["changes"] = [
            {"path": "tracked.txt", "kind": "modified", "summary": "Correct"},
            {"path": "tracked.txt", "kind": "deleted", "summary": "Incorrect kind"},
        ]
        result = self.capture(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        database = self.repo / ".memory-hub" / "memory.db"
        with sqlite3.connect(database) as connection:
            values = connection.execute("SELECT summary, git_verified FROM changes ORDER BY id").fetchall()
            changed_files = json.loads(connection.execute("SELECT git_changed_files FROM sessions").fetchone()[0])
        self.assertEqual(values, [("Correct", 1), ("Incorrect kind", 0)])
        self.assertEqual(changed_files[0]["path"], "tracked.txt")

    def test_server_start_api_reuse_and_stop(self):
        payload = capture_payload(summary="Server-visible state")
        payload["capabilities"] = [{
            "name": "Local dashboard", "status": "implemented", "summary": "Serves repository memory",
            "file_paths": ["scripts/memory_hub.py"]
        }]
        self.assertEqual(self.capture(payload).returncode, 0)
        server_path = self.repo / ".memory-hub" / "server.json"
        state = self.start_server()

        health = self.fetch_json(f"http://127.0.0.1:{state['port']}/api/health")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["pid"], state["pid"])
        overview = self.fetch_json(f"http://127.0.0.1:{state['port']}/api/overview")
        self.assertEqual(overview["repository"]["state"], "Server-visible state")
        self.assertEqual(overview["counts"]["capabilities"], 1)

        reused = self.run_cli("serve", timeout=5)
        self.assertEqual(reused.returncode, 0, reused.stderr)
        self.assertEqual(json.loads(server_path.read_text(encoding="utf-8"))["pid"], state["pid"])

        stopped = self.run_cli("stop", timeout=8)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn("server stopped", stopped.stdout)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.server_health(state):
            time.sleep(0.05)
        self.assertFalse(self.server_health(state))
        self.assertFalse(server_path.exists())
        self.server_state = None

    def test_api_session_details_include_children_and_record_editable_fields(self):
        payload = capture_payload(summary="Detailed session")
        payload["tasks"] = [{
            "id": "task-local", "title": "Session child task", "status": "planned",
            "summary": "Visible in the ledger",
        }]
        payload["evidence"] = [{
            "id": "evidence-local", "kind": "test", "summary": "Session child evidence",
        }]
        payload["relationships"] = [{
            "from_id": "evidence-local", "type": "supports", "to_id": "task-local",
        }]
        captured = self.capture(payload)
        self.assertEqual(captured.returncode, 0, captured.stderr)
        session_id = captured.stdout.split("Captured session ", 1)[1].split(" ", 1)[0]
        task_id = self.record_id("tasks", "title", "Session child task")

        details = self.api_request(f"/api/sessions/{session_id}")
        self.assertEqual(details["session"]["id"], session_id)
        for collection in (*ENTITY_ARRAYS, "relationships"):
            self.assertIn(collection, details)
        self.assertEqual(details["tasks"][0]["id"], task_id)
        self.assertEqual(details["evidence"][0]["summary"], "Session child evidence")
        self.assertEqual(len(details["relationships"]), 1)

        record = self.api_request(f"/api/records/task/{task_id}")
        self.assertEqual(record["id"], task_id)
        self.assertIn("editable_fields", record)
        self.assertIn("summary", record["editable_fields"])
        self.assertIn("tests", record["editable_fields"])
        self.assertNotIn("id", record["editable_fields"])
        self.assertNotIn("session_id", record["editable_fields"])

    def test_api_patch_scalar_and_array_updates_search_index(self):
        payload = capture_payload(summary="Patch fixture")
        payload["tasks"] = [{
            "title": "Patchable task", "status": "planned",
            "summary": "Legacyquartz wording", "tests": ["tests/legacy_case.py"],
        }]
        self.assertEqual(self.capture(payload).returncode, 0)
        task_id = self.record_id("tasks", "title", "Patchable task")

        updated = self.api_request(
            f"/api/records/task/{task_id}", method="PATCH",
            body={"summary": "Moderncobalt wording", "tests": ["tests/new_case.py", "tests/edge_case.py"]},
        )
        self.assertEqual(updated["summary"], "Moderncobalt wording")
        self.assertEqual(updated["tests"], ["tests/new_case.py", "tests/edge_case.py"])
        old_search = self.api_request("/api/search?q=legacyquartz")
        new_search = self.api_request("/api/search?q=moderncobalt")
        self.assertNotIn(task_id, [record["id"] for record in old_search["results"]])
        self.assertEqual([record["id"] for record in new_search["results"]], [task_id])

    def test_api_patch_rejects_invalid_and_unsafe_updates(self):
        payload = capture_payload(summary="Validation fixture")
        payload["tasks"] = [{
            "title": "Guarded task", "status": "planned", "summary": "Keep valid",
            "file_paths": ["src/safe.py"], "source": "agent", "confirmation": "agent-inferred",
        }]
        self.assertEqual(self.capture(payload).returncode, 0)
        task_id = self.record_id("tasks", "title", "Guarded task")
        endpoint = f"/api/records/task/{task_id}"
        cases = [
            ({"id": "tsk_replacement"}, "unknown or immutable field"),
            ({"status": "invented"}, "expected abandoned|blocked|completed|deferred|in-progress|planned"),
            ({"summary": "api_key=supersecretcredentialvalue"}, "suspected credential assignment"),
            ({"file_paths": ["../outside.py"]}, "expected a safe repository-relative path"),
            ({"confirmation": "human-confirmed"}, "human confirmation requires source 'human'"),
        ]
        for patch, message in cases:
            with self.subTest(patch=patch):
                error = self.api_request(endpoint, method="PATCH", body=patch, expected_status=400)
                self.assertIn(message, error["error"])
        record = self.api_request(endpoint)
        self.assertEqual(record["summary"], "Keep valid")
        self.assertEqual(record["status"], "planned")

    def test_api_delete_and_unknown_resource_responses(self):
        payload = capture_payload(summary="Deletion fixture")
        payload["tasks"] = [
            {"id": "free", "title": "Disposable task", "status": "planned", "summary": "Unreferenced"},
            {"id": "used", "title": "Referenced task", "status": "planned", "summary": "Referenced"},
        ]
        payload["changes"] = [{
            "path": "src/consumer.py", "kind": "modified", "summary": "References task",
            "task_ids": ["used"],
        }]
        self.assertEqual(self.capture(payload).returncode, 0)
        free_id = self.record_id("tasks", "title", "Disposable task")
        used_id = self.record_id("tasks", "title", "Referenced task")

        self.api_request(f"/api/records/task/{free_id}", method="DELETE", expected_status=204)
        self.api_request(f"/api/records/task/{free_id}", expected_status=404)
        conflict = self.api_request(
            f"/api/records/task/{used_id}", method="DELETE", expected_status=409,
        )
        self.assertIn("record is referenced by", conflict["error"])
        self.assertIn("changes", conflict["error"])

        self.api_request("/api/not-a-route", expected_status=404)
        self.api_request("/api/sessions/ses_missing", expected_status=404)
        self.api_request("/api/records/task/tsk_missing", expected_status=404)
        self.api_request(
            "/api/records/not-a-type/unknown", method="PATCH", body={"summary": "x"},
            expected_status=404,
        )
        self.api_request(
            "/api/records/task/tsk_missing", method="DELETE", expected_status=404,
        )

    @staticmethod
    def fetch_json(url):
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def server_health(state):
        try:
            data = MemoryHubCLITests.fetch_json(
                f"http://127.0.0.1:{state['port']}/api/health"
            )
            return data.get("token") == state["token"] and data.get("pid") == state["pid"]
        except (OSError, ValueError, urllib.error.URLError):
            return False


if __name__ == "__main__":
    unittest.main()
