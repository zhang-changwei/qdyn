import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List


class QdynDB:

    def __init__(self):
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def init_db(self, db_path: str = "data/qdyn_users.db") -> None:
        """Create tables and store the module-level connection."""

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 3000")
            self._conn.execute("PRAGMA foreign_keys = ON")

            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    username   TEXT UNIQUE NOT NULL,
                    hashed_pw  TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS task_owners (
                    task_id    TEXT PRIMARY KEY,
                    username   TEXT NOT NULL,
                    job_ids    TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (username) REFERENCES users(username)
                );
                CREATE TABLE IF NOT EXISTS queued_submissions (
                    task_id       TEXT PRIMARY KEY,
                    username      TEXT NOT NULL,
                    pool_name     TEXT NOT NULL,
                    payload_json  TEXT NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'QUEUED',
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    claimed_at    TEXT DEFAULT NULL,
                    submitted_at  TEXT DEFAULT NULL,
                    last_error    TEXT DEFAULT NULL
                );
            """)
            self._conn.commit()

            # Migrate: add optional metadata columns if they don't exist yet
            self._migrate_task_metadata()


    def _migrate_task_metadata(self) -> None:
        """Add formula, num_atoms, prev_task_id, worker, and pool_name columns
        to task_owners if missing.  Also backfills pool_name for historical
        rows that have worker='local_slurm'."""
        assert self._conn is not None
        cursor = self._conn.execute("PRAGMA table_info(task_owners)")
        existing = {row["name"] for row in cursor.fetchall()}
        migrations = {
            "formula": "ALTER TABLE task_owners ADD COLUMN formula TEXT DEFAULT NULL",
            "num_atoms": "ALTER TABLE task_owners ADD COLUMN num_atoms INTEGER DEFAULT NULL",
            "prev_task_id": "ALTER TABLE task_owners ADD COLUMN prev_task_id TEXT DEFAULT NULL",
            "worker": "ALTER TABLE task_owners ADD COLUMN worker TEXT DEFAULT NULL",
            "pool_name": "ALTER TABLE task_owners ADD COLUMN pool_name TEXT DEFAULT NULL",
            "task_name": "ALTER TABLE task_owners ADD COLUMN task_name TEXT DEFAULT NULL",
            "stru_hash": "ALTER TABLE task_owners ADD COLUMN stru_hash TEXT DEFAULT NULL",
            "stru_format": "ALTER TABLE task_owners ADD COLUMN stru_format TEXT DEFAULT NULL",
        }
        added_pool_name = False
        for col, ddl in migrations.items():
            if col not in existing:
                self._conn.execute(ddl)
                if col == "pool_name":
                    added_pool_name = True

        # Backfill pool_name for pre-pool rows: worker='local_slurm' -> pool_name='local_slurm'
        if added_pool_name:
            self._conn.execute(
                "UPDATE task_owners SET pool_name = 'local_slurm' "
                "WHERE worker = 'local_slurm' AND pool_name IS NULL"
            )
        self._conn.commit()

    def get_db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return self._conn
    

    def close_db(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.close()
                self._conn = None


    def create_user(self, username: str, hashed_pw: str) -> None:
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "INSERT INTO users (username, hashed_pw) VALUES (?, ?)",
                (username, hashed_pw),
            )
            conn.commit()


    def get_user(self, username: str) -> dict | None:
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None


    def assign_task(
        self,
        task_id: str,
        username: str,
        job_ids: dict,
        pool_name: str | None = None,
    ) -> None:
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "INSERT INTO task_owners (task_id, username, job_ids, pool_name) "
                "VALUES (?, ?, ?, ?)",
                (task_id, username, json.dumps(job_ids), pool_name),
            )
            conn.commit()


    def get_user_tasks(self, username: str) -> list[str]:
        conn = self.get_db()
        with self._lock:
            rows = conn.execute(
                "SELECT task_id FROM task_owners WHERE username = ? ORDER BY created_at DESC",
                (username,),
            ).fetchall()
        return [row["task_id"] for row in rows]


    def get_task_owner(self, task_id: str) -> str | None:
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT username FROM task_owners WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row["username"] if row else None


    def get_task_job_ids(self, task_id: str) -> dict:
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT job_ids FROM task_owners WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return {}
        return json.loads(row["job_ids"])


    def delete_task_record(self, task_id: str) -> None:
        conn = self.get_db()
        with self._lock:
            conn.execute("DELETE FROM task_owners WHERE task_id = ?", (task_id,))
            conn.commit()

    def update_task_metadata(
        self,
        task_id: str,
        *,
        task_name: str | None = None,
        formula: str | None = None,
        num_atoms: int | None = None,
        prev_task_id: str | None = None,
        worker: str | None = None,
        pool_name: str | None = None,
        stru_hash: str | None = None,
        stru_format: str | None = None,
    ) -> None:
        """Persist task name, structure metadata, resume lineage, worker, pool, and trajectory hash/format."""
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "UPDATE task_owners SET task_name = ?, formula = ?, num_atoms = ?, "
                "prev_task_id = ?, worker = ?, pool_name = ?, stru_hash = ?, stru_format = ? "
                "WHERE task_id = ?",
                (task_name, formula, num_atoms, prev_task_id, worker, pool_name,
                 stru_hash, stru_format, task_id),
            )
            conn.commit()

    def update_task_name(self, task_id: str, task_name: str | None) -> bool:
        """Update only the task_name for a task. Returns True if the row was found."""
        conn = self.get_db()
        with self._lock:
            cursor = conn.execute(
                "UPDATE task_owners SET task_name = ? WHERE task_id = ?",
                (task_name, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_task_metadata(self, task_id: str) -> dict | None:
        """Return task metadata including stru_hash for a task (or None)."""
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT task_name, formula, num_atoms, prev_task_id, worker, pool_name, stru_hash, stru_format "
                "FROM task_owners WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_task_created_at(self, task_id: str) -> float | None:
        """Return task creation time as a UTC timestamp, or None if unavailable."""
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT created_at FROM task_owners WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None

        created_at = row["created_at"]
        if not created_at:
            return None

        try:
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                return None

        if dt.tzinfo is None or dt.utcoffset() is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def get_queued_payload(self, task_id: str) -> str | None:
        """Return the payload_json for a queued task, or None if not found."""
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT payload_json FROM queued_submissions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return row["payload_json"] if row else None

    # ------------------------------------------------------------------
    # Queued submissions helpers
    # ------------------------------------------------------------------

    def enqueue_submission(
        self,
        task_id: str,
        username: str,
        pool_name: str,
        payload_json: str,
    ) -> None:
        """Insert a new QUEUED submission into the waiting queue."""
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "INSERT INTO queued_submissions "
                "(task_id, username, pool_name, payload_json, status) "
                "VALUES (?, ?, ?, ?, 'QUEUED')",
                (task_id, username, pool_name, payload_json),
            )
            conn.commit()

    def claim_queued(self, task_id: str) -> bool:
        """Atomically transition a task from QUEUED to DISPATCHING.

        Uses BEGIN IMMEDIATE for write-lock acquisition.
        Returns True if the claim succeeded, False otherwise (e.g. already
        claimed or cancelled).
        """
        conn = self.get_db()
        with self._lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status FROM queued_submissions WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if row is None or row["status"] != "QUEUED":
                    conn.execute("COMMIT")
                    return False
                conn.execute(
                    "UPDATE queued_submissions "
                    "SET status = 'DISPATCHING', claimed_at = datetime('now') "
                    "WHERE task_id = ?",
                    (task_id,),
                )
                conn.execute("COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def mark_submitted(
        self, task_id: str, job_ids: dict, worker: str
    ) -> None:
        """Mark a queued task as SUBMITTED after successful dispatch.

        Also records the runtime worker name for traceability.
        """
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "UPDATE queued_submissions "
                "SET status = 'SUBMITTED', submitted_at = datetime('now') "
                "WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()

    def mark_queue_failed(self, task_id: str, error: str) -> None:
        """Mark a queued task as FAILED, recording the error message.

        If the task was DISPATCHING, it transitions to FAILED.
        The last_error field is always updated for diagnostic purposes.
        """
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "UPDATE queued_submissions "
                "SET status = 'FAILED', last_error = ? "
                "WHERE task_id = ? AND status IN ('QUEUED', 'DISPATCHING')",
                (error, task_id),
            )
            conn.commit()

    def cancel_queued(self, task_id: str, username: str) -> bool:
        """Cancel a queued task.  Only QUEUED tasks can be cancelled.

        Validates that the requesting user owns the task.
        Returns True if cancellation succeeded, False if the task was not
        found, not owned by the user, or not in QUEUED status.
        """
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT username, status FROM queued_submissions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            if row["username"] != username:
                return False
            if row["status"] != "QUEUED":
                return False
            conn.execute(
                "UPDATE queued_submissions SET status = 'CANCELLED' WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()
            return True

    def get_queued_status(self, task_id: str) -> dict | None:
        """Return queue entry for a single task, or None if not in queue.

        Used by get_task_detail() to detect QUEUED/DISPATCHING/FAILED/CANCELLED
        tasks that have not (or only partially) been submitted.
        """
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT task_id, pool_name, status, created_at, last_error "
                "FROM queued_submissions "
                "WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_queued_for_user(self, username: str) -> List[dict]:
        """Return all queued submissions for a user, ordered by creation time."""
        conn = self.get_db()
        with self._lock:
            rows = conn.execute(
                "SELECT task_id, pool_name, status, created_at, last_error "
                "FROM queued_submissions "
                "WHERE username = ? "
                "ORDER BY created_at ASC",
                (username,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_queued(self) -> List[dict]:
        """Return all tasks in QUEUED status, ordered by creation time (FIFO).

        This is the primary query used by the poller to find work.
        """
        conn = self.get_db()
        with self._lock:
            rows = conn.execute(
                "SELECT task_id, username, pool_name, payload_json "
                "FROM queued_submissions "
                "WHERE status = 'QUEUED' "
                "ORDER BY created_at ASC",
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_stale_dispatching(self, timeout_seconds: int = 60) -> int:
        """Recover tasks stuck in DISPATCHING state beyond the timeout.

        For each stale DISPATCHING task, checks whether it was actually
        submitted (task_owners.job_ids is non-empty).  If so, marks it
        SUBMITTED instead of re-queuing, to avoid duplicate dispatch.
        Returns the number of recovered rows.
        """
        conn = self.get_db()
        with self._lock:
            # Find stale DISPATCHING tasks
            rows = conn.execute(
                "SELECT q.task_id, t.job_ids "
                "FROM queued_submissions q "
                "LEFT JOIN task_owners t ON q.task_id = t.task_id "
                "WHERE q.status = 'DISPATCHING' "
                "  AND q.claimed_at < datetime('now', ? || ' seconds')",
                (str(-timeout_seconds),),
            ).fetchall()

            count = 0
            for row in rows:
                task_id = row["task_id"]
                job_ids = row["job_ids"]
                # Check if job_ids is non-empty (actually submitted).
                # This covers the crash window between submit_flow()
                # and mark_submitted(): if job_ids were filled in by
                # update_task_dispatch_info(), the flow is real.
                actually_submitted = bool(
                    job_ids and job_ids != '{}' and job_ids != '[]'
                )
                if actually_submitted:
                    # Flow was submitted — mark as SUBMITTED, not re-queued
                    conn.execute(
                        "UPDATE queued_submissions "
                        "SET status = 'SUBMITTED', "
                        "    submitted_at = datetime('now') "
                        "WHERE task_id = ?",
                        (task_id,),
                    )
                else:
                    # Flow was not submitted — safe to re-queue
                    conn.execute(
                        "UPDATE queued_submissions "
                        "SET status = 'QUEUED', claimed_at = NULL "
                        "WHERE task_id = ?",
                        (task_id,),
                    )
                count += 1
            conn.commit()
            return count

    def release_claim(self, task_id: str) -> None:
        """Transition a DISPATCHING task back to QUEUED.

        Used by the poller when worker selection succeeds during the
        pre-check but fails under the dispatch lock (TOCTOU race).
        """
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "UPDATE queued_submissions "
                "SET status = 'QUEUED', claimed_at = NULL "
                "WHERE task_id = ? AND status = 'DISPATCHING'",
                (task_id,),
            )
            conn.commit()

    def update_task_dispatch_info(
        self, task_id: str, job_ids: dict, worker: str
    ) -> None:
        """Update job_ids and worker for an existing task_owners row.

        Called by the poller after a queued task is successfully
        dispatched.  The row was created with empty ``job_ids`` when
        the task was enqueued, so this fills in the actual values.
        """
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "UPDATE task_owners SET job_ids = ?, worker = ? "
                "WHERE task_id = ?",
                (json.dumps(job_ids), worker, task_id),
            )
            conn.commit()


qdyndb = QdynDB()
