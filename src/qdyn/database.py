import json
import os
import sqlite3
from typing import Optional

class QdynDB:

    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None

    def init_db(self, db_path: str = "data/qdyn_users.db") -> None:
        """Create tables and store the module-level connection."""

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=True)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")  # 开启读写并行
        self._conn.execute("PRAGMA synchronous = NORMAL")  # 兼顾性能和数据安全，断电最多丢几秒数据
        self._conn.execute("PRAGMA busy_timeout = 3000")  # 抢不到锁最多等待3秒，避免直接报错
        self._conn.execute("PRAGMA foreign_keys = ON")  # 开启外键约束，你这里用了外键必须开！

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


    def get_db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return self._conn
    

    def close_db(self) -> None:
        if self._conn is not None:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None


    def create_user(self, username: str, hashed_pw: str) -> None:
        conn = self.get_db()
        conn.execute(
            "INSERT INTO users (username, hashed_pw) VALUES (?, ?)",
            (username, hashed_pw),
        )
        conn.commit()


    def get_user(self, username: str) -> Optional[dict]:
        conn = self.get_db()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


    def assign_task(self, task_id: str, username: str, job_ids: dict) -> None:
        conn = self.get_db()
        conn.execute(
            "INSERT INTO task_owners (task_id, username, job_ids) VALUES (?, ?, ?)",
            (task_id, username, json.dumps(job_ids)),
        )
        conn.commit()


    def get_user_tasks(self, username: str) -> list[str]:
        conn = self.get_db()
        rows = conn.execute(
            "SELECT task_id FROM task_owners WHERE username = ? ORDER BY created_at DESC",
            (username,),
        ).fetchall()
        return [row["task_id"] for row in rows]


    def get_task_owner(self, task_id: str) -> Optional[str]:
        conn = self.get_db()
        row = conn.execute(
            "SELECT username FROM task_owners WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row["username"] if row else None


    def get_task_job_ids(self, task_id: str) -> dict:
        conn = self.get_db()
        row = conn.execute(
            "SELECT job_ids FROM task_owners WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return {}
        return json.loads(row["job_ids"])


    def delete_task_record(self, task_id: str) -> None:
        conn = self.get_db()
        conn.execute("DELETE FROM task_owners WHERE task_id = ?", (task_id,))
        conn.commit()

qdyndb = QdynDB()