"""5500 milestones. Shared identity, isolated project records; no GitHub requirement."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import ROOT
from .learning import people_with_photos

SECTIONS = {"1135": "11:35 a.m.", "255": "2:55 p.m."}

def stamp():
    return datetime.now(timezone.utc).isoformat()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Member(Strict):
    name: str = Field(min_length=1, max_length=100)
    slack_id: str | None = Field(default=None, pattern=r"^[UW][A-Z0-9]+$")


class Progress(Strict):
    entrepreneur: str = Field(default="", max_length=160)
    company: str = Field(default="", max_length=160)
    interview: Literal["unknown", "outreach", "scheduled", "completed"] = "unknown"
    scheduled_date: date | None = None
    completed_date: date | None = None
    paper: Literal["unknown", "planning", "drafting", "ready", "submitted"] = "unknown"
    creative: Literal["unknown", "planning", "drafting", "ready", "submitted"] = "unknown"
    creative_format: str = Field(default="", max_length=120)
    next_step: str = Field(default="", max_length=600)
    owner: str = Field(default="", max_length=100)
    target_date: date | None = None
    blocker: str = Field(default="", max_length=600)
    document_url: str = Field(default="", max_length=1000)
    creative_url: str = Field(default="", max_length=1000)
    source_url: str = Field(default="", max_length=1000)
    source_date: date | None = None
    presentation_date: date | None = None
    verified: bool = False

    @field_validator("document_url", "creative_url", "source_url")
    @classmethod
    def safe_link(cls, value):
        if value:
            parsed = urlsplit(value)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or any(c.isspace() for c in value)):
                raise ValueError("Links must be complete HTTPS URLs")
        return value

    @model_validator(mode="after")
    def dates(self):
        if self.completed_date and self.interview != "completed":
            raise ValueError("A completion date requires an interview marked completed")
        if self.completed_date and self.completed_date > datetime.now(timezone.utc).date():
            raise ValueError("A completed interview cannot have a future date")
        return self


class Group(Strict):
    id: str = Field(pattern=r"^(1135|255)-[a-z0-9-]+$")
    section: Literal["1135", "255"]
    name: str = Field(min_length=1, max_length=100)
    members: list[Member] = Field(min_length=1, max_length=10)
    channel_id: str = Field(pattern=r"^[CG][A-Z0-9]+$")
    progress: Progress = Field(default_factory=Progress)


class Roster(Strict):
    workspace_id: str = Field(pattern=r"^T[A-Z0-9]+$")
    instructor_slack_ids: list[str] = Field(min_length=1)
    groups: list[Group] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct(self):
        ids = [g.id for g in self.groups]
        members = [m.slack_id for g in self.groups for m in g.members if m.slack_id]
        if len(ids) != len(set(ids)) or len(members) != len(set(members)):
            raise ValueError("Groups and student Slack identities must be distinct")
        if set(members) & set(self.instructor_slack_ids):
            raise ValueError("Instructor identities cannot be student identities")
        import re
        if (len(self.instructor_slack_ids) != len(set(self.instructor_slack_ids))
                or any(not re.fullmatch(r"[UW][A-Z0-9]+", value) for value in self.instructor_slack_ids)):
            raise ValueError("Instructor Slack identities must be distinct valid member IDs")
        if any(not g.id.startswith(g.section + "-") for g in self.groups):
            raise ValueError("A group ID must belong to its section")
        return self


class Update(Strict):
    revision: int = Field(ge=0)
    progress: Progress


class Store:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS groups (id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    progress TEXT NOT NULL, reporter TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, group_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, progress TEXT NOT NULL, reporter TEXT NOT NULL, updated TEXT NOT NULL);

            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        Path(self.path).chmod(0o600)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, group):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO groups VALUES (?,?,?,?,?)",
                       (group.id, 0, group.progress.model_dump_json(), "Imported source", stamp()))
            return dict(db.execute("SELECT * FROM groups WHERE id=?", (group.id,)).fetchone())

    def save(self, group, update, reporter):
        self.get(group)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM groups WHERE id=?", (group.id,)).fetchone()
            if previous["revision"] != update.revision:
                raise HTTPException(409, "This group changed. Reload its latest update before saving.")
            revision = previous["revision"] + 1
            payload, at = update.progress.model_dump_json(), stamp()
            db.execute("INSERT INTO history(group_id,revision,progress,reporter,updated) VALUES (?,?,?,?,?)",
                       (group.id, previous["revision"], previous["progress"], previous["reporter"], previous["updated"]))
            db.execute("UPDATE groups SET revision=?, progress=?, reporter=?, updated=? WHERE id=?",
                       (revision, payload, reporter, at, group.id))
        return self.get(group)


def create_progress(settings, directory, shared_session, logout, slack_enabled, mirror=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    public = urlsplit(settings.workspace_url)
    base = public.path.removesuffix("/workspace") + "/5500/2026/fall"
    auth = urlsplit(settings.dashboard_url).path
    store = Store(settings.progress_db_path)
    app.state.store = store

    def session(request: Request):
        signed_in = shared_session(request)
        user = directory.progress_identity(signed_in["id"])
        if not user:
            raise HTTPException(403, "This course is not on your roster")
        return {**user, "csrf": signed_in["csrf"]}

    def view(group, row, user):
        progress = Progress.model_validate_json(row["progress"])
        return {"id": group.id, "name": group.name, "section": group.section,
                "member_profiles": people_with_photos(mirror,group.members) if mirror else [],
                "members": [m.name for m in group.members], "revision": row["revision"],
                "progress": progress.model_dump(mode="json"), "reporter": row["reporter"],
                "updated": row["updated"],
                "editable": user["role"] == "instructor" or group.id in user["groups"],
                "slack_url": f"https://app.slack.com/client/{directory.roster().workspace_id}/{group.channel_id}"}

    @app.get("/api/session")
    def current(request: Request):
        try:
            user = session(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            user = None
        return {"user": user, "slack_enabled": slack_enabled, "preview": False}

    @app.post("/api/logout")
    def sign_out(request: Request, user=Depends(session)):
        return logout(request)

    @app.get("/api/sections/{section}")
    def board(section: str, user=Depends(session)):
        if section not in user["sections"]:
            raise HTTPException(403, "This section is not on your course roster")
        groups = [view(g, store.get(g), user) for g in directory.roster().groups if g.section == section]
        return {"section": section, "time": SECTIONS[section], "groups": groups, "checked": stamp(),
                "due": f"2026-11-10T{'11:35' if section == '1135' else '14:55'}:00-05:00"}

    @app.put("/api/groups/{group_id}")
    def edit(group_id: str, update: Update, user=Depends(session)):
        group = next((g for g in directory.roster().groups if g.id == group_id), None)
        if not group or group.section not in user["sections"]:
            raise HTTPException(404, "Group not found")
        if user["role"] != "instructor":
            if group.id not in user["groups"]:
                raise HTTPException(403, "You can update your own group")
            if update.progress.verified:
                raise HTTPException(403, "Only the instructor can verify a group update")
            current_progress = Progress.model_validate_json(store.get(group)["progress"])
            if update.progress.presentation_date != current_progress.presentation_date:
                raise HTTPException(403, "Presentation dates are assigned by the instructor")
        return view(group, store.save(group, update, user["name"]), user)

    @app.get("/api/groups/{group_id}/history")
    def history(group_id: str, user=Depends(session)):
        group = next((g for g in directory.roster().groups if g.id == group_id), None)
        if not group or group.section not in user["sections"]:
            raise HTTPException(404, "Group not found")
        with store.connect() as db:
            rows = db.execute("SELECT * FROM history WHERE group_id=? ORDER BY revision DESC LIMIT 30", (group_id,))
            return {"updates": [view(group, dict(row), user) for row in rows]}

    @app.get("/{section}/")
    def home(section: str):
        if section not in SECTIONS:
            raise HTTPException(404, "Section not found")
        html = (ROOT / "web/progress/index.html").read_text().replace("__BASE__", base)
        html = html.replace("__SECTION__", section)
        html = html.replace(base + "/auth/slack?section=" + section,
                            auth + "/auth/slack?next=5500-" + section)
        html = html.replace('<nav><a href="/entr/5500/">',
                            '<nav><a href="/entr/workspace/">My courses</a><a href="/entr/5500/">')
        return HTMLResponse(html)

    app.mount("/assets", StaticFiles(directory=ROOT / "web/progress"), name="progress-assets")
    return app
