"""Small, transactional single-instance store; no secrets in records or logs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import Course


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value):
    return hashlib.sha256(stable_json(value).encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pin_history (
                    id TEXT PRIMARY KEY, sprint TEXT NOT NULL, project TEXT NOT NULL,
                    value TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, student_id TEXT NOT NULL, sprint TEXT NOT NULL,
                    kind TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
                    private INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    due_at TEXT NOT NULL, created_at TEXT NOT NULL,
                    provider_ts TEXT, detail TEXT, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prompts (
                    channel TEXT NOT NULL, ts TEXT NOT NULL, meeting_id TEXT NOT NULL,
                    sprint TEXT NOT NULL, PRIMARY KEY(channel,ts)
                );
                CREATE TABLE IF NOT EXISTS digests (
                    id TEXT PRIMARY KEY, sprint TEXT NOT NULL, provider TEXT NOT NULL,
                    body TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, action TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL
                );
            """)
        Path(path).chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, stable_json(value)))

    def course(self) -> Course | None:
        value = self.get("course")
        return Course.model_validate(value) if value else None

    def save_course(self, course: Course):
        old = self.course()
        if old and old.id != course.id:
            raise ValueError("one offering per database; use a new database for another course")
        if old:
            with self.connect() as db:
                has_records = db.execute("SELECT 1 FROM entries LIMIT 1").fetchone() or db.execute(
                    "SELECT 1 FROM outbox LIMIT 1").fetchone()
            if has_records:
                students = {s.id: s for s in course.students}
                projects = {p.id: p for p in course.projects}
                for student in old.students:
                    new = students.get(student.id)
                    if new and (new.slack_id, new.github_login, new.project_id) != (
                        student.slack_id, student.github_login, student.project_id
                    ):
                        raise ValueError("Recorded student identity mappings require an explicit data migration")
                for project in old.projects:
                    new = projects.get(project.id)
                    if new and (new.channel_id, new.repository) != (project.channel_id, project.repository):
                        raise ValueError("Recorded project mappings require an explicit data migration")
        self.set("course", course.model_dump(mode="json"))
        self.audit("course_updated", {"hash": content_hash(course.model_dump(mode="json")),
                                      "active": course.active})

    def audit(self, action, detail):
        with self.connect() as db:
            db.execute("INSERT INTO audit(action,detail,at) VALUES (?,?,?)",
                       (action, stable_json(detail), now_iso()))

    def add_entry(self, id, student_id, sprint, kind, text, source, private=False):
        with self.connect() as db:
            db.execute("""INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET text=excluded.text, source=excluded.source""",
                       (id, student_id, sprint, kind, text, stable_json(source), int(private), now_iso()))

    def entries(self, sprint, student_id=None):
        query, args = "SELECT * FROM entries WHERE sprint=?", [sprint]
        if student_id:
            query += " AND student_id=?"
            args.append(student_id)
        with self.connect() as db:
            rows = db.execute(query + " ORDER BY created_at DESC", args).fetchall()
        return [{**dict(r), "source": json.loads(r["source"])} for r in rows]

    def enqueue(self, id, kind, payload, due_at):
        digest = content_hash(payload)
        with self.connect() as db:
            row = db.execute("SELECT payload_hash FROM outbox WHERE id=?", (id,)).fetchone()
            if row:
                if row["payload_hash"] != digest:
                    raise ValueError("delivery ID already exists with different content; reconcile it first")
                return False
            db.execute("""INSERT INTO outbox
                (id,kind,payload,payload_hash,due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?)""",
                       (id, kind, stable_json(payload), digest, due_at, now_iso(), now_iso()))
        return True

    def outbox(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM outbox ORDER BY created_at DESC LIMIT 500").fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def claim(self, at):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM outbox WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT 1",
                             (at,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE outbox SET status='delivering',updated_at=? WHERE id=?", (at, row["id"]))
        return {**dict(row), "payload": json.loads(row["payload"])}

    def finish(self, id, status, provider_ts=None, detail=None):
        with self.connect() as db:
            db.execute("UPDATE outbox SET status=?,provider_ts=?,detail=?,updated_at=? WHERE id=?",
                       (status, provider_ts, detail, now_iso(), id))

    def recover(self):
        with self.connect() as db:
            db.execute("""UPDATE outbox SET status='uncertain',detail='Process ended during delivery',updated_at=?
                          WHERE status='delivering'""", (now_iso(),))

    def prompt(self, channel, ts):
        with self.connect() as db:
            row = db.execute("SELECT * FROM prompts WHERE channel=? AND ts=?", (channel, ts)).fetchone()
        return dict(row) if row else None

    def add_prompt(self, channel, ts, meeting_id, sprint):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO prompts VALUES (?,?,?,?)", (channel, ts, meeting_id, sprint))

    def save_digest(self, id, sprint, provider, body):
        with self.connect() as db:
            db.execute("INSERT INTO digests VALUES (?,?,?,?,?)", (id, sprint, provider, stable_json(body), now_iso()))

    def digest(self, id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM digests WHERE id=?", (id,)).fetchone()
        return {**dict(row), "body": json.loads(row["body"])} if row else None

    def digest_list(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,sprint,provider,created_at FROM digests ORDER BY created_at DESC LIMIT 30")
            return [dict(r) for r in rows]

    def purge(self, cutoff):
        with self.connect() as db:
            for table in ("entries", "digests"):
                db.execute(f"DELETE FROM {table} WHERE created_at<?", (cutoff,))
            db.execute("DELETE FROM pin_history WHERE created_at<?", (cutoff,))
            # Expire abandoned jobs instead of retaining old learning text indefinitely.
            db.execute("UPDATE outbox SET status='expired' WHERE created_at<? AND status IN ('pending','failed')",
                       (cutoff,))
            # Keep delivery IDs/hashes as tombstones so old jobs cannot be replayed.
            db.execute("""UPDATE outbox SET payload='{}',detail='Content removed by retention policy'
                          WHERE created_at<? AND status IN ('sent','cancelled','expired')""", (cutoff,))
            for row in db.execute("""SELECT key,value FROM settings WHERE key LIKE 'evidence/%'
                                   OR key LIKE 'project_evidence/%' OR key LIKE 'pin/%'
                                   OR key LIKE 'github_notifications/%' OR key LIKE 'showcase/%'
                                   OR key LIKE 'showcase_media/%'""").fetchall():
                value = json.loads(row["value"])
                if value.get("collected_at", value.get("updated_at", "")) < cutoff:
                    db.execute("DELETE FROM settings WHERE key=?", (row["key"],))

    def backup(self, target):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        Path(target).chmod(0o600)
