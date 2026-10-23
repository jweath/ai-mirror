"""Read-through course directory. Source rosters grant access; names never match identities."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from .config import StrictModel
from .pinup import safe_url
from .progress import SECTIONS, Roster


class EnrollmentObservation(StrictModel):
    section: Literal["1135", "255"]
    count: int = Field(ge=0, le=1000)
    observed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source: str = Field(min_length=1, max_length=200)
    source_url: str = ""


class DirectorySources(StrictModel):
    group_roster_url: str = ""
    group_roster_observed_on: str = ""
    enrollment_observations: list[EnrollmentObservation] = Field(default_factory=list)
    enrollment_snapshot: "EnrollmentSnapshot | None" = None


class EnrolledStudent(StrictModel):
    slack_id: str = Field(pattern=r"^[UW][A-Z0-9]+$")
    source_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    section: Literal["1135", "255"]


class EnrollmentSnapshot(StrictModel):
    checked_at: datetime
    source: str = Field(min_length=1, max_length=200)
    students: list[EnrolledStudent] = Field(max_length=500)

    @model_validator(mode="after")
    def distinct(self):
        if self.checked_at.utcoffset() is None:
            raise ValueError("A roster snapshot needs its timezone")
        keys = [(s.slack_id, s.section) for s in self.students]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate section enrollment")
        return self


class Directory:
    def __init__(self, settings, mirror):
        self.settings, self.mirror = settings, mirror

    def roster(self):
        if not self.settings.progress_roster_path:
            raise HTTPException(503, "Connect the 5500 group roster")
        try:
            roster = Roster.model_validate_json(Path(self.settings.progress_roster_path).read_text())
            course = self.mirror.course()
            if not course or roster.workspace_id != course.workspace_id:
                raise ValueError("workspace_mismatch")
            return roster
        except (OSError, ValueError):
            raise HTTPException(503, "The 5500 roster needs review") from None

    def sources(self):
        if not self.settings.directory_sources_path:
            return DirectorySources()
        try:
            sources = DirectorySources.model_validate_json(Path(self.settings.directory_sources_path).read_text())
            safe_url(sources.group_roster_url)
            for entry in sources.enrollment_observations:
                safe_url(entry.source_url)
            return sources
        except (OSError, ValueError):
            raise HTTPException(503, "The directory source record needs review") from None

    def mirror_identity(self, user_id):
        course = self.mirror.course()
        if not course:
            return None
        if user_id in course.instructor_slack_ids:
            return {"id": user_id, "name": "John", "role": "instructor"}
        student = course.student_by_slack(user_id)
        if student:
            return {"id": user_id, "name": student.name, "role": "student"}
        if user_id in course.viewer_slack_ids:
            return {"id": user_id, "name": "Course member", "role": "student"}
        return None

    def progress_identity(self, user_id):
        roster = self.roster()
        if user_id in roster.instructor_slack_ids:
            return {"id": user_id, "name": "John", "role": "instructor",
                    "sections": list(SECTIONS), "groups": []}
        snapshot = self.sources().enrollment_snapshot
        if snapshot:
            enrolled = [s for s in snapshot.students if s.slack_id == user_id]
            if not enrolled:
                return None
            sections = [s.section for s in enrolled]
            groups = [g for g in roster.groups if g.section in sections
                      and any(m.slack_id == user_id for m in g.members)]
            name = next((m.name for g in groups for m in g.members if m.slack_id == user_id), enrolled[0].name)
            return {"id": user_id, "name": name, "role": "student",
                    "sections": sections, "groups": [g.id for g in groups]}
        for group in roster.groups:
            for member in group.members:
                if member.slack_id == user_id:
                    return {"id": user_id, "name": member.name, "role": "student",
                            "sections": [group.section], "groups": [group.id]}
        return None

    def identity(self, user_id):
        mirror = self.mirror_identity(user_id)
        try:
            progress = self.progress_identity(user_id)
        except HTTPException:
            # A disconnected 5500 source cannot revoke a valid 5000 session.
            progress = None
        if not mirror and not progress:
            return None
        grants = []
        if mirror:
            grants.append({"course": "5000", "offering_id": self.mirror.course().id,
                           "section": "115", "role": mirror["role"]})
        if progress:
            grants.extend({"course": "5500", "offering_id": "entr-5500-fall-2026",
                           "section": section, "role": progress["role"]}
                          for section in progress["sections"])
        return {"id": user_id, "name": (mirror or progress)["name"], "grants": grants,
                "role": "instructor" if any(g["role"] == "instructor" for g in grants) else "student"}

    def snapshot(self, allowed_courses):
        people, sections = {}, []

        def add(slack_id, name, course, section, source_id, group_id, group_name, source):
            person = people.setdefault(slack_id, {"id": "slack:" + slack_id,
                                                "slack_id": slack_id, "name": name, "enrollments": []})
            person["enrollments"].append({"course": course, "section": section,
                                           "offering_id": self.mirror.course().id if course == "5000"
                                           else "entr-5500-fall-2026",
                                           "source_id": source_id, "group_id": group_id,
                                           "group_name": group_name, "source": source})

        if "5000" in allowed_courses:
            course = self.mirror.course()
            if course:
                projects = {p.id: p for p in course.projects}
                for student in course.students:
                    add(student.slack_id, student.name, "5000", "115", student.id,
                        student.project_id, projects[student.project_id].name, "AI Mirror course map")
                sections.append({"course": "5000", "section": "115", "label": "1:15 p.m.",
                                 "members": len(course.students), "groups": len(course.projects),
                                 "source": "AI Mirror course map", "connection": "connected"})
        alerts = []
        if "5500" in allowed_courses:
            try:
                roster = self.roster()
                sources = self.sources()
            except HTTPException as exc:
                alerts.append({"id": "roster-5500", "course": "5500", "title": exc.detail,
                               "detail": "5500 access is closed until its source is valid.", "href": ""})
                roster, sources = None, DirectorySources()
            if roster:
                if sources.enrollment_snapshot:
                    for student in sources.enrollment_snapshot.students:
                        group = next((g for g in roster.groups if g.section == student.section
                                      and any(m.slack_id == student.slack_id for m in g.members)), None)
                        name = next((m.name for m in group.members if m.slack_id == student.slack_id),
                                    student.name) if group else student.name
                        add(student.slack_id, name, "5500", student.section, student.source_id,
                            group.id if group else None, group.name if group else "Unassigned",
                            sources.enrollment_snapshot.source)
                        if not group:
                            alerts.append({"id": "ungrouped-" + student.slack_id, "course": "5500",
                                           "section": student.section, "title": name + " has no group assignment",
                                           "detail": "The participation roster includes this student. Confirm their "
                                                     "group in the matching sheet.",
                                           "href": sources.group_roster_url})
                    enrolled = {(s.slack_id, s.section) for s in sources.enrollment_snapshot.students}
                    for group in roster.groups:
                        for member in group.members:
                            if member.slack_id and (member.slack_id, group.section) not in enrolled:
                                alerts.append({"id": "enrollment-review-" + member.slack_id, "course": "5500",
                                               "section": group.section, "title": member.name + " needs a roster check",
                                               "detail": "Present on a group sheet, absent from the enrollment snapshot. "
                                                         "Course access follows the enrollment snapshot.",
                                               "href": sources.group_roster_url})
                else:
                    for group in roster.groups:
                        for member in group.members:
                            if member.slack_id:
                                add(member.slack_id, member.name, "5500", group.section, member.slack_id,
                                    group.id, group.name, "5500 group matching sheets")
                for section, label in SECTIONS.items():
                    groups = [g for g in roster.groups if g.section == section]
                    count = sum(len(g.members) for g in groups)
                    enrolled_count = sum(s.section == section for s in sources.enrollment_snapshot.students) \
                        if sources.enrollment_snapshot else None
                    sections.append({"course": "5500", "section": section, "label": label,
                                     "members": count, "groups": len(groups),
                                     "source": "5500 group matching sheets", "connection": "connected",
                                     "source_url": sources.group_roster_url,
                                     "observed_on": sources.group_roster_observed_on,
                                     "enrolled": enrolled_count,
                                     "enrollment_checked_at": sources.enrollment_snapshot.checked_at.isoformat()
                                     if sources.enrollment_snapshot else None})
                    observations = [o for o in sources.enrollment_observations if o.section == section]
                    if observations and not sources.enrollment_snapshot:
                        latest = max(observations, key=lambda o: o.observed_on)
                        if latest.count != count:
                            alerts.append({"id": "enrollment-" + section, "course": "5500",
                                           "title": f"Reconcile the {label} roster",
                                           "detail": f"{count} group members; {latest.count} enrollments reported "
                                                     f"on {latest.observed_on}. Check the current enrollment "
                                                     "before changing either roster.",
                                           "href": sources.group_roster_url})
        return {"people": sorted(people.values(), key=lambda p: p["name"].casefold()),
                "sections": sections, "alerts": alerts}
