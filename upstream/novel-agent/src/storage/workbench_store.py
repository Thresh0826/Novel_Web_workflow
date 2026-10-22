"""Persistent manual handoffs, kept outside all source manuscript folders."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def data_directory():
    return Path(os.environ.get("NOVEL_WORKBENCH_DATA", Path(__file__).parents[4] / "workbench-data"))


@contextmanager
def database():
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / "workbench.sqlite3", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL, chapter INTEGER NOT NULL,
            stage TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id),
            created_at TEXT NOT NULL, reviewer TEXT NOT NULL, verdict TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id),
            report_id INTEGER NOT NULL REFERENCES reports(id), created_at TEXT NOT NULL,
            note TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS automatic_runs (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL, chapter INTEGER NOT NULL,
            status TEXT NOT NULL, step TEXT NOT NULL, message TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS tasks_book_chapter ON tasks(book_id, chapter);
    """)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_task(book_id, chapter, stage, payload):
    task_id = uuid4().hex
    with database() as conn:
        conn.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                     (task_id, book_id, chapter, stage, now(), json.dumps(payload, ensure_ascii=False)))
    return task_id


def task_records(book_id, chapter=None):
    with database() as conn:
        query = "SELECT * FROM tasks WHERE book_id=?"
        args = [book_id]
        if chapter is not None:
            query += " AND chapter=?"
            args.append(chapter)
        rows = conn.execute(query + " ORDER BY created_at DESC, rowid DESC", args).fetchall()
        return [dict(row) for row in rows]


def get_task(task_id):
    with database() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None


def reports_for(task_id):
    with database() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM reports WHERE task_id=? ORDER BY id DESC", (task_id,))]


def save_report(task_id, reviewer, verdict, content):
    with database() as conn:
        cursor = conn.execute("INSERT INTO reports(task_id,created_at,reviewer,verdict,content) VALUES(?,?,?,?,?)",
                              (task_id, now(), reviewer, verdict, content))
        return cursor.lastrowid


def latest_approval(task_id):
    with database() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
        return dict(row) if row else None


def save_approval(task_id, report_id, note):
    with database() as conn:
        latest = conn.execute("SELECT id FROM reports WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
        if latest is None or latest["id"] != report_id:
            return False
        conn.execute("INSERT INTO approvals(task_id,report_id,created_at,note) VALUES(?,?,?,?)",
                     (task_id, report_id, now(), note))
        return True


def create_run(book_id, chapter, options=None):
    run_id = uuid4().hex
    with database() as conn:
        timestamp = now()
        conn.execute("INSERT INTO automatic_runs(id,book_id,chapter,status,step,message,created_at,updated_at,result) VALUES(?,?,?,?,?,?,?,?,?)",
                     (run_id, book_id, chapter, "queued", "queued", "已排队，等待本机模型运行", timestamp, timestamp,
                      json.dumps({"options": options or {}}, ensure_ascii=False)))
    return run_id


def update_run(run_id, *, status=None, step=None, message=None, result=None):
    updates = {"updated_at": now()}
    if status is not None: updates["status"] = status
    if step is not None: updates["step"] = step
    if message is not None: updates["message"] = message
    if result is not None:
        existing = get_run(run_id)
        merged = {**(existing or {}).get("result", {}), **result}
        updates["result"] = json.dumps(merged, ensure_ascii=False)
    assignments = ",".join(f"{key}=?" for key in updates)
    with database() as conn:
        conn.execute(f"UPDATE automatic_runs SET {assignments} WHERE id=?", (*updates.values(), run_id))


def get_run(run_id):
    with database() as conn:
        row = conn.execute("SELECT * FROM automatic_runs WHERE id=?", (run_id,)).fetchone()
        if not row: return None
        result = dict(row)
        result["result"] = json.loads(result["result"])
        return result


def runs_for(book_id, chapter=None):
    with database() as conn:
        query = "SELECT id FROM automatic_runs WHERE book_id=?"
        args = [book_id]
        if chapter is not None:
            query += " AND chapter=?"
            args.append(chapter)
        ids = [row["id"] for row in conn.execute(query + " ORDER BY created_at DESC", args)]
    return [get_run(run_id) for run_id in ids]
