from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Student(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    slack_id: str = Field(pattern=r"^[UW][A-Z0-9]+$")
    github_login: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
    project_id: str


class Project(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    channel_id: str = Field(pattern=r"^[CG][A-Z0-9]+$")
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class Meeting(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    at: datetime
    kind: Literal["exit_ticket", "peer_review"] = "exit_ticket"

    @field_validator("at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("meeting.at must include its UTC offset")
        return value


class Course(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    name: str
    workspace_id: str = Field(pattern=r"^T[A-Z0-9]+$")
    timezone: str = "America/New_York"
    sprint: str = Field(pattern=r"^[a-z0-9_-]+$")
    instructor_slack_ids: list[str] = Field(min_length=1)
    students: list[Student] = Field(min_length=1, max_length=300)
    projects: list[Project] = Field(min_length=1, max_length=300)
    meetings: list[Meeting] = Field(default_factory=list)
    active: bool = False
    activated_at: datetime | None = None
    github_enabled: bool = False
    retention_days: int = Field(default=90, ge=7, le=730)

    @model_validator(mode="after")
    def coherent(self):
        ZoneInfo(self.timezone)
        for values, label in [([s.id for s in self.students], "student IDs"),
                              ([s.slack_id for s in self.students], "Slack IDs"),
                              ([s.github_login.lower() for s in self.students], "GitHub accounts"),
                              ([p.id for p in self.projects], "project IDs"),
                              ([p.channel_id for p in self.projects], "project channels"),
                              ([m.id for m in self.meetings], "meeting IDs")]:
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label}")
        projects = {p.id for p in self.projects}
        if any(s.project_id not in projects for s in self.students):
            raise ValueError("each student must reference a configured project")
        if any(not re.fullmatch(r"[UW][A-Z0-9]+", s) for s in self.instructor_slack_ids):
            raise ValueError("instructor_slack_ids must contain Slack member IDs")
        if set(self.instructor_slack_ids) & {s.slack_id for s in self.students}:
            raise ValueError("instructors and students need distinct IDs")
        if self.active and (not self.activated_at or self.activated_at.utcoffset() is None):
            raise ValueError("activation requires an explicit timezone-aware activated_at; no backfill")
        return self

    def project(self, student: Student) -> Project:
        return next(p for p in self.projects if p.id == student.project_id)

    def student_by_slack(self, slack_id: str) -> Student | None:
        return next((s for s in self.students if s.slack_id == slack_id), None)


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/mirror.db"
    admin_token: str = ""
    slack_token: str = ""
    slack_signing_secret: str = ""
    github_token: str = ""
    sends_enabled: bool = False
    openai_key: str = ""
    openai_model: str = ""
    digest_provider: str = "extractive"
    background_enabled: bool = True
    public_url: str = "http://127.0.0.1:8000"

    @classmethod
    def from_env(cls):
        return cls(
            db_path=os.getenv("MIRROR_DB_PATH", "data/mirror.db"),
            admin_token=os.getenv("MIRROR_ADMIN_TOKEN", ""),
            slack_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            sends_enabled=os.getenv("MIRROR_SEND_ENABLED", "false").lower() == "true",
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", ""),
            digest_provider=os.getenv("MIRROR_DIGEST_PROVIDER", "extractive"),
            background_enabled=os.getenv("MIRROR_BACKGROUND_ENABLED", "true").lower() == "true",
            public_url=os.getenv("MIRROR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
        )


ROOT = Path(os.getenv("MIRROR_ASSET_ROOT", str(Path(__file__).resolve().parents[2])))
