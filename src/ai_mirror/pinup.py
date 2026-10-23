"""Private project projection. Source text is never interpreted as instructions."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .config import StrictModel
from .learning import photo_url
from .store import content_hash


def safe_url(value):
    if not value:
        return value
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ValueError("Use a complete HTTPS link without embedded credentials")
    return value


class ProjectPin(StrictModel):
    shared: bool = False
    goal: str = Field(default="", max_length=1200)
    next_test: str = Field(default="", max_length=1200)
    commitment: str = Field(default="", max_length=600)
    commitment_date: date | None = None
    live_url: str = Field(default="", max_length=2000)
    source_url: str = Field(default="", max_length=2000)
    source_kind: Literal["student_statement", "instructor_note"] = "instructor_note"
    source_at: datetime | None = None

    @field_validator("goal", "next_test", "commitment", "live_url", "source_url")
    @classmethod
    def trimmed(cls, value):
        return value.strip()

    @field_validator("live_url", "source_url")
    @classmethod
    def https(cls, value):
        return safe_url(value)

    @field_validator("source_at")
    @classmethod
    def aware(cls, value):
        if value and value.utcoffset() is None:
            raise ValueError("Source time must include its UTC offset")
        return value

    @model_validator(mode="after")
    def sourced(self):
        if any((self.goal, self.next_test, self.commitment, self.live_url)) and not self.source_url:
            raise ValueError("Link the source for this pin, including its product URL")
        if self.commitment_date and not self.commitment:
            raise ValueError("A commitment date needs a stated commitment")
        return self


class PinUpdate(StrictModel):
    pin: ProjectPin
    expected_revision: str | None = None


class PinConflict(ValueError):
    pass


def save_pin(store, project_id, update, now=None):
    course = store.course()
    if not course or not any(p.id == project_id for p in course.projects):
        raise KeyError(project_id)
    key = f"pin/{course.sprint}/{project_id}"
    value = {"pin": update.pin.model_dump(mode="json"),
             "updated_at": (now or datetime.now(timezone.utc)).isoformat()}
    # A second tab cannot silently overwrite a pin reviewed in the first tab.
    with store.connect() as db:
        import json
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        previous = json.loads(row["value"]) if row else None
        revision = content_hash(previous) if previous else None
        if revision != update.expected_revision:
            raise PinConflict("This pin changed. Refresh and review the current version before saving.")
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
    store.audit("project_pin_updated", {"project_id": project_id, "sprint": course.sprint,
                                        "revision": content_hash(value)})
    return {**value, "revision": content_hash(value)}


def board(store, now=None, shared=False):
    now = now or datetime.now(timezone.utc)
    course = store.course()
    if not course:
        return {"course": None, "sprint": None, "projects": [], "generated_at": now.isoformat()}
    entries = store.entries(course.sprint)
    projects = []
    for project in course.projects:
        owners = [s for s in course.students if s.project_id == project.id]
        ids = {s.id for s in owners}
        pin = store.get(f"pin/{course.sprint}/{project.id}")
        if shared and pin and not pin["pin"].get("shared"):
            pin = None
        evidence = store.get(f"project_evidence/{course.sprint}/{project.id}")
        captured = [{k: entry[k] for k in ("id", "student_id", "text", "source", "created_at")}
                    for entry in entries if entry["student_id"] in ids
                    and not entry["private"] and entry["kind"] in ("exit_ticket", "project_update")][:12]
        checked = evidence.get("collected_at") if evidence else None
        stale = not checked or datetime.fromisoformat(checked) < now - timedelta(hours=48)
        pin_age = (pin["pin"].get("source_at") or pin["updated_at"]) if pin else None
        projects.append({
            "id": project.id, "name": project.name,
            "repository_url": f"https://github.com/{project.repository}" if project.repository else None,
            "issues_url": f"https://github.com/{project.repository}/issues" if project.repository else None,
            "channel_url": f"https://app.slack.com/client/{course.workspace_id}/{project.channel_id}",
            "owners": [{"id": s.id, "name": s.name, "slack_id":s.slack_id,
                        "photo":photo_url(store.get("learning_profiles",{}).get(s.slack_id,""))} for s in owners],
            "pin": pin["pin"] if pin else ProjectPin().model_dump(mode="json"),
            "pin_updated_at": pin["updated_at"] if pin else None,
            "pin_stale": bool(pin_age and datetime.fromisoformat(pin_age) < now - timedelta(days=7)),
            "revision": content_hash(pin) if pin else None,
            "evidence": evidence, "evidence_stale": stale,
            "collection_enabled": course.github_enabled, "updates": captured,
            "slack_collection": store.get(f"slack_collection/{project.id}"),
            "github_notifications": store.get(f"github_notifications/{course.sprint}/{project.id}", {}),
        })
    return {"course": course.name, "sprint": course.sprint, "projects": projects,
            "active": course.active, "github_enabled": course.github_enabled,
            "slack_enabled": course.slack_enabled, "generated_at": now.isoformat()}
