import json
import os
import sqlite3
import threading
from typing import Optional


class QdynDB:

    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None
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
            """)
            self._conn.commit()

            # Migrate: add optional metadata columns if they don't exist yet
            self._migrate_task_metadata()


    def _migrate_task_metadata(self) -> None:
        """Add formula, num_atoms, prev_task_id, and worker columns if missing."""
        assert self._conn is not None
        cursor = self._conn.execute("PRAGMA table_info(task_owners)")
        existing = {row["name"] for row in cursor.fetchall()}
        migrations = {
            "formula": "ALTER TABLE task_owners ADD COLUMN formula TEXT DEFAULT NULL",
            "num_atoms": "ALTER TABLE task_owners ADD COLUMN num_atoms INTEGER DEFAULT NULL",
            "prev_task_id": "ALTER TABLE task_owners ADD COLUMN prev_task_id TEXT DEFAULT NULL",
            "worker": "ALTER TABLE task_owners ADD COLUMN worker TEXT DEFAULT NULL",
        }
        for col, ddl in migrations.items():
            if col not in existing:
                self._conn.execute(ddl)
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


    def get_user(self, username: str) -> Optional[dict]:
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None


    def assign_task(self, task_id: str, username: str, job_ids: dict) -> None:
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "INSERT INTO task_owners (task_id, username, job_ids) VALUES (?, ?, ?)",
                (task_id, username, json.dumps(job_ids)),
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


    def get_task_owner(self, task_id: str) -> Optional[str]:
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
        formula: Optional[str] = None,
        num_atoms: Optional[int] = None,
        prev_task_id: Optional[str] = None,
        worker: Optional[str] = None,
    ) -> None:
        """Persist structure metadata, resume lineage, and worker for a task."""
        conn = self.get_db()
        with self._lock:
            conn.execute(
                "UPDATE task_owners SET formula = ?, num_atoms = ?, prev_task_id = ?, worker = ? WHERE task_id = ?",
                (formula, num_atoms, prev_task_id, worker, task_id),
            )
            conn.commit()

    def get_task_metadata(self, task_id: str) -> Optional[dict]:
        """Return formula, num_atoms, prev_task_id, and worker for a task (or None)."""
        conn = self.get_db()
        with self._lock:
            row = conn.execute(
                "SELECT formula, num_atoms, prev_task_id, worker FROM task_owners WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

qdyndb = QdynDB()
