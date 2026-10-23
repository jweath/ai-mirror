"""Read the published course brief; never accept source instructions or credentials."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

import httpx
from pydantic import Field, field_validator

from .config import StrictModel
from .pinup import safe_url


class Action(StrictModel):
    id: str
    title: str = Field(max_length=500)
    detail: str = Field(max_length=3000)
    due: datetime | None = None
    until: datetime | None = None
    source_url: str
    href: str

    @field_validator("source_url", "href")
    @classmethod
    def link(cls, value):
        if value.startswith("/entr/") and not any(c.isspace() or ord(c) < 32 for c in value):
            return value
        return safe_url(value)

    @field_validator("due", "until")
    @classmethod
    def aware(cls, value):
        if value and value.utcoffset() is None:
            raise ValueError("A deadline needs its timezone")
        return value


class CourseBrief(StrictModel):
    course: Literal["5000", "5500"]
    section: Literal["115", "1135", "255"]
    title: str
    updated_at: datetime
    through: datetime
    home_url: str
    actions: list[Action] = Field(max_length=100)

    @field_validator("updated_at", "through")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Publication time needs its timezone")
        return value

    @field_validator("home_url")
    @classmethod
    def home(cls, value):
        if value not in ("/entr/5000/", "/entr/5500/"):
            raise ValueError("Unknown course home")
        return value


class Publication(StrictModel):
    version: Literal[1]
    courses: list[CourseBrief] = Field(max_length=3)


class CourseContext:
    def __init__(self, transport=None):
        self.transport, self.checked, self.value = transport, 0, None
        self.lock = Lock()

    def read(self):
        with self.lock:
            if time.monotonic() - self.checked < 60 and self.value:
                return self.value
            try:
                # Fixed public source, with no auth headers and no redirects.
                with httpx.Client(timeout=5, transport=self.transport) as client:
                    result = client.get("https://entr-site-production.up.railway.app/entr/course-context.json")
                    result.raise_for_status()
                    if len(result.content) > 200_000:
                        raise ValueError("oversize_publication")
                    publication = Publication.model_validate_json(result.content)
                self.value = {"connected": True, "courses": publication.courses,
                              "checked_at": datetime.now(timezone.utc).isoformat()}
            except (httpx.HTTPError, ValueError):
                self.value = {"connected": False, "courses": [], "checked_at": None}
            self.checked = time.monotonic()
            return self.value

    def for_section(self, course, section, now=None):
        now = now or datetime.now(timezone.utc)
        result = self.read()
        brief = next((b for b in result["courses"] if b.course == course and b.section == section), None)
        if not brief:
            return {"connected": False, "actions": [], "expired": False}
        expired = brief.through < now
        actions = [a.model_dump(mode="json") for a in brief.actions
                   if not expired and (not a.due or a.due >= now) and (not a.until or a.until >= now)]
        actions.sort(key=lambda a: a["due"] or "9999")
        return {"connected": True, "expired": expired, "actions": actions[:6],
                "updated_at": brief.updated_at.isoformat(), "through": brief.through.isoformat()}
