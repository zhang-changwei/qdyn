import json
import sqlite3
from typing import Optional

_conn: Optional[sqlite3.Connection] = None


def init_db(db_path: str = "data/qdyn_users.db") -> sqlite3.Connection:
    """Create tables and store the module-level connection."""
    global _conn
    import os
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.executescript("""
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
    _conn.commit()
    return _conn


def get_db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _conn


def create_user(conn: sqlite3.Connection, username: str, hashed_pw: str) -> None:
    conn.execute(
        "INSERT INTO users (username, hashed_pw) VALUES (?, ?)",
        (username, hashed_pw),
    )
    conn.commit()


def get_user(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    return dict(row) if row else None


def assign_task(
    conn: sqlite3.Connection, task_id: str, username: str, job_ids: dict
) -> None:
    conn.execute(
        "INSERT INTO task_owners (task_id, username, job_ids) VALUES (?, ?, ?)",
        (task_id, username, json.dumps(job_ids)),
    )
    conn.commit()


def get_user_tasks(conn: sqlite3.Connection, username: str) -> list[str]:
    rows = conn.execute(
        "SELECT task_id FROM task_owners WHERE username = ? ORDER BY created_at DESC",
        (username,),
    ).fetchall()
    return [row["task_id"] for row in rows]


def get_task_owner(conn: sqlite3.Connection, task_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT username FROM task_owners WHERE task_id = ?", (task_id,)
    ).fetchone()
    return row["username"] if row else None


def get_task_job_ids(conn: sqlite3.Connection, task_id: str) -> dict:
    row = conn.execute(
        "SELECT job_ids FROM task_owners WHERE task_id = ?", (task_id,)
    ).fetchone()
    if row is None:
        return {}
    return json.loads(row["job_ids"])


def delete_task_record(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("DELETE FROM task_owners WHERE task_id = ?", (task_id,))
    conn.commit()
