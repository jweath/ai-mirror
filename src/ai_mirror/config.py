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
    github_login: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
    project_id: str


class Project(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    channel_id: str = Field(pattern=r"^[CG][A-Z0-9]+$")
    repository: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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
    viewer_slack_ids: list[str] = Field(default_factory=list)
    students: list[Student] = Field(min_length=1, max_length=300)
    projects: list[Project] = Field(min_length=1, max_length=300)
    meetings: list[Meeting] = Field(default_factory=list)
    active: bool = False
    activated_at: datetime | None = None
    github_enabled: bool = False
    slack_enabled: bool = False
    github_slack_app_id: str | None = Field(default=None, pattern=r"^A[A-Z0-9]+$")
    retention_days: int = Field(default=90, ge=7, le=730)

    @model_validator(mode="after")
    def coherent(self):
        ZoneInfo(self.timezone)
        for values, label in [([s.id for s in self.students], "student IDs"),
                              ([s.slack_id for s in self.students], "Slack IDs"),
                              ([s.github_login.lower() for s in self.students if s.github_login], "GitHub accounts"),
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
        if (any(not re.fullmatch(r"[UW][A-Z0-9]+", s) for s in self.viewer_slack_ids)
                or len(self.viewer_slack_ids) != len(set(self.viewer_slack_ids))
                or set(self.viewer_slack_ids) & set(self.instructor_slack_ids)):
            raise ValueError("viewer_slack_ids must contain distinct non-instructor Slack member IDs")
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
    github_app_config_path: str = ""
    github_app_slug: str = ""
    github_webhook_secret: str = ""
    github_bootstrap_enabled: bool = False
    github_app_id: str = ""
    github_app_private_key: str = ""
    rehearsal_channel_id: str = ""
    sends_enabled: bool = False
    openai_key: str = ""
    openai_model: str = ""
    digest_provider: str = "extractive"
    background_enabled: bool = True
    public_url: str = "http://127.0.0.1:8000"
    dashboard_url: str = "https://jweath.com/entr/5000/2026/fall"
    session_secret: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    learning_url: str = "https://participation-api-production.up.railway.app/learning/snapshot"
    learning_token: str = ""
    workspace_enabled: bool = False
    workspace_url: str = "https://jweath.com/entr/workspace"
    progress_roster_path: str = ""
    progress_db_path: str = "data/progress.db"
    directory_sources_path: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            db_path=os.getenv("MIRROR_DB_PATH", "data/mirror.db"),
            admin_token=os.getenv("MIRROR_ADMIN_TOKEN", ""),
            slack_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_app_config_path=os.getenv("GITHUB_APP_CONFIG_PATH", ""),
            github_app_slug=os.getenv("GITHUB_APP_SLUG", ""),
            github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
            github_bootstrap_enabled=os.getenv("GITHUB_APP_BOOTSTRAP_ENABLED", "false").lower()=="true",
            github_app_id=os.getenv("GITHUB_APP_ID", ""),
            github_app_private_key=os.getenv("GITHUB_APP_PRIVATE_KEY", ""),
            rehearsal_channel_id=os.getenv("MIRROR_REHEARSAL_CHANNEL_ID", ""),
            sends_enabled=os.getenv("MIRROR_SEND_ENABLED", "false").lower() == "true",
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", ""),
            digest_provider=os.getenv("MIRROR_DIGEST_PROVIDER", "extractive"),
            background_enabled=os.getenv("MIRROR_BACKGROUND_ENABLED", "true").lower() == "true",
            public_url=os.getenv("MIRROR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
            dashboard_url=os.getenv("MIRROR_DASHBOARD_URL", "https://jweath.com/entr/5000/2026/fall").rstrip("/"),
            session_secret=os.getenv("MIRROR_SESSION_SECRET", ""),
            slack_client_id=os.getenv("SLACK_CLIENT_ID", ""),
            slack_client_secret=os.getenv("SLACK_CLIENT_SECRET", ""),
            learning_url=os.getenv("COURSE_LEARNING_URL", "https://participation-api-production.up.railway.app/learning/snapshot"),
            learning_token=os.getenv("COURSE_LEARNING_TOKEN", ""),
            workspace_enabled=os.getenv("COURSE_WORKSPACE_ENABLED", "false").lower() == "true",
            workspace_url=os.getenv("COURSE_WORKSPACE_URL", "https://jweath.com/entr/workspace").rstrip("/"),
            progress_roster_path=os.getenv("PROGRESS_ROSTER_PATH", ""),
            progress_db_path=os.getenv("PROGRESS_DB_PATH", "data/progress.db"),
            directory_sources_path=os.getenv("COURSE_DIRECTORY_SOURCES_PATH", ""),
        )


ROOT = Path(os.getenv("MIRROR_ASSET_ROOT", str(Path(__file__).resolve().parents[2])))
