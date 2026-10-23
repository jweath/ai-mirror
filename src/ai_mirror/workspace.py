"""One course entry and private instructor view over source-owned records."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT
from .course_context import CourseContext
from .pinup import board
from .progress import SECTIONS, Progress

TITLES = {"5000": "AI & The Entrepreneur", "5500": "Introduction to Entrepreneurship"}
SLACK_CHANNELS = {"115": "C0BRD8TGN83", "1135": "C0BRFH9B7MK", "255": "C0BRMBNE0TT"}


def instructor_courses(user):
    return {g["course"] for g in user["grants"] if g["role"] == "instructor"}


def create_workspace(settings, mirror, directory, progress, shared_session, logout, slack_enabled):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    prefix = urlsplit(settings.workspace_url).path
    context = CourseContext()
    app.state.context = context

    def instructor(user=Depends(shared_session)):
        if not instructor_courses(user):
            raise HTTPException(403, "Instructor access required")
        return user

    def offering(course, section):
        return {"course": course, "section": section, "title": TITLES[course],
                "offering_id": mirror.course().id if course == "5000" else "entr-5500-fall-2026",
                "label": "1:15 p.m." if course == "5000" else SECTIONS[section],
                "home_url": f"/entr/{course}/", "assignments_url": f"/entr/{course}/assignments/",
                "overview_url": "/entr/5000/2026/fall/" if course == "5000"
                                else f"/entr/5500/2026/fall/{section}/",
                "brief": context.for_section(course, section)}

    def page(mode):
        html = (ROOT / "web/workspace/index.html").read_text()
        html = html.replace("__BASE__", prefix).replace("__MODE__", mode)
        html = html.replace("__AUTH__", urlsplit(settings.dashboard_url).path)
        return HTMLResponse(html)

    @app.get("/")
    def home():
        return page("home")

    @app.get("/instructor/")
    def instructor_home(request: Request):
        try:
            user = shared_session(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            return RedirectResponse(settings.dashboard_url + "/auth/slack?next=instructor-home", status_code=303)
        if not instructor_courses(user):
            raise HTTPException(403, "Instructor access required")
        return page("instructor")

    @app.get("/api/session")
    def current(request: Request):
        try:
            user = shared_session(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            user = None
        return {"user": user, "slack_enabled": slack_enabled}

    @app.post("/api/logout")
    def sign_out(request: Request, user=Depends(shared_session)):
        return logout(request)

    @app.get("/api/home")
    def student_home(user=Depends(shared_session)):
        course_map = mirror.course()
        courses = []
        for grant in user["grants"]:
            row = offering(grant["course"], grant["section"])
            row["role"] = grant["role"]
            row["slack_url"] = (f"https://app.slack.com/client/{course_map.workspace_id}/"
                                + SLACK_CHANNELS[grant["section"]])
            if grant["course"] == "5000":
                student = course_map.student_by_slack(user["id"])
                if student:
                    project = course_map.project(student)
                    row["my_work"] = {"name": project.name,
                                      "href": f"https://app.slack.com/client/{course_map.workspace_id}/{project.channel_id}",
                                      "document_url": "", "next_step": "", "source_at": None,
                                      "source_url": ""}
                    if project.repository:
                        row["my_work"]["document_url"] = "https://github.com/" + project.repository
                    pin = mirror.get(f"pin/{course_map.sprint}/{project.id}")
                    if pin and pin["pin"].get("shared"):
                        row["my_work"]["next_step"] = pin["pin"].get("next_test", "")
                        row["my_work"]["source_at"] = pin["pin"].get("source_at") or pin["updated_at"]
                        row["my_work"]["source_url"] = pin["pin"].get("source_url", "")
            else:
                member = directory.progress_identity(user["id"])
                group = next((g for g in directory.roster().groups
                              if g.section == grant["section"] and g.id in member["groups"]), None)
                if group:
                    saved = progress.get(group)
                    state = Progress.model_validate_json(saved["progress"])
                    row["my_work"] = {"name": group.name,
                                      "href": f"https://app.slack.com/client/{course_map.workspace_id}/{group.channel_id}",
                                      "document_url": state.document_url, "next_step": state.next_step,
                                      "source_at": saved["updated"] if saved["revision"] else state.source_date,
                                      "source_url": state.source_url}
            courses.append(row)
        return {"name": user["name"], "courses": courses,
                "instructor": bool(instructor_courses(user)),
                "name_practice_url": "https://the-face-book-production.up.railway.app",
                "grades_url": "https://elc.uga.edu/"}

    @app.get("/api/directory")
    def people(user=Depends(instructor)):
        return directory.snapshot(instructor_courses(user))

    @app.get("/api/overview")
    def overview(user=Depends(instructor)):
        allowed = instructor_courses(user)
        snapshot = directory.snapshot(allowed)
        alerts, courses, changes, projects = list(snapshot["alerts"]), [], [], []
        course_map = mirror.course()
        if "5000" in allowed and course_map:
            result = board(mirror)
            full = sum(bool(p["evidence"] and p["evidence"].get("complete")) for p in result["projects"])
            for project in result["projects"]:
                item = {"course": "5000", "section": "115", "name": project["name"],
                        "next_step": project["pin"]["next_test"], "blocker": "",
                        "href": project["channel_url"], "overview_url": "/entr/5000/2026/fall/",
                        "source_url": project["pin"]["source_url"],
                        "source_at": project["pin"].get("source_at")}
                projects.append(item)
                for update in project["updates"]:
                    if not update["text"].strip() or update["text"].lstrip().startswith("/"):
                        continue
                    source = update["source"]
                    href = source.get("url") or source.get("permalink") or project["channel_url"]
                    changes.append({"course": "5000", "section": "115", "name": project["name"],
                                    "text": update["text"][:350], "at": source.get("at") or update["created_at"],
                                    "href": href, "kind": "Owner update"})
                for evidence in (project["evidence"] or {}).get("items", [])[:8]:
                    if evidence.get("at") and evidence.get("url"):
                        changes.append({"course": "5000", "section": "115", "name": project["name"],
                                        "text": evidence.get("text", "").splitlines()[0][:350]
                                        if evidence.get("text") else "Repository updated",
                                        "at": evidence["at"], "href": evidence["url"],
                                        "kind": "GitHub " + evidence.get("type", "change").replace("_", " ")})
            courses.append({**offering("5000", "115"), "students": len(course_map.students),
                            "groups": len(result["projects"]),
                            "metrics": [{"label": "Slack channels connected", "value": sum(
                                bool(p["slack_collection"] and p["slack_collection"].get("complete"))
                                for p in result["projects"])},
                                        {"label": "GitHub reads complete", "value": full}]})
            if full < len(result["projects"]):
                alerts.append({"id": "github-coverage", "course": "5000", "title": "Finish GitHub connections",
                               "detail": f"{full} of {len(result['projects'])} repositories have complete direct reads. "
                                         "Missing access does not establish inactivity.",
                               "href": "/entr/5000/2026/fall/"})
        if "5500" in allowed:
            try:
                roster = directory.roster()
            except HTTPException:
                roster = None
            if roster:
                for section in SECTIONS:
                    groups = [g for g in roster.groups if g.section == section]
                    states = []
                    for group in groups:
                        saved = progress.get(group)
                        state = Progress.model_validate_json(saved["progress"])
                        states.append(state)
                        href = f"/entr/5500/2026/fall/{section}/"
                        projects.append({"course": "5500", "section": section, "name": group.name,
                                         "next_step": state.next_step, "blocker": state.blocker,
                                         "href": href, "overview_url": href,
                                         "source_url": state.source_url, "source_at": state.source_date})
                        if saved["revision"]:
                            changes.append({"course": "5500", "section": section, "name": group.name,
                                            "text": state.next_step or "Group milestones updated",
                                            "at": saved["updated"], "href": href,
                                            "kind": "Instructor verified" if state.verified else "Group report"})
                        if state.blocker:
                            alerts.append({"id": "blocker-" + group.id, "course": "5500", "section": section,
                                           "title": group.name + " needs help", "detail": state.blocker, "href": href})
                    source_section = next((s for s in snapshot["sections"]
                                           if s["course"] == "5500" and s["section"] == section), {})
                    courses.append({**offering("5500", section),
                                    "students": source_section.get("enrolled")
                                    if source_section.get("enrolled") is not None else sum(len(g.members) for g in groups),
                                    "groups": len(groups), "metrics": [
                                        {"label": "Interviews reported complete",
                                         "value": sum(s.interview == "completed" for s in states)},
                                        {"label": "Next steps recorded", "value": sum(bool(s.next_step) for s in states)}]})
        notifications = None
        if "5000" in allowed:
            notifications = {"mirror_enabled": settings.sends_enabled and bool(course_map and course_map.active),
                             "hold": bool(mirror.get("delivery_hold", False)),
                             "scheduled": len(course_map.meetings) if course_map else 0,
                             "pending": sum(r["status"] == "pending" for r in mirror.outbox()),
                             "href": "/entr/5000/2026/fall/instructor"}
        participation = {"connected": False,
                         "detail": "Participation review remains in instOS. A live read connection is not configured here."}
        if "5500" in allowed:
            try:
                enrollment = directory.sources().enrollment_snapshot
                if enrollment:
                    participation["enrollment_checked_at"] = enrollment.checked_at.isoformat()
                    participation["detail"] = ("Enrollment snapshot checked "
                        + enrollment.checked_at.strftime("%b %d, %Y")
                        + ". Live check-ins, corrections and exports remain in instOS.")
            except HTTPException:
                pass
        return {"courses": courses, "alerts": alerts, "projects": projects,
                "changes": sorted(changes, key=lambda c: c["at"] or "", reverse=True)[:30],
                "notifications": notifications, "participation": participation,
                "checked_at": datetime.now(timezone.utc).isoformat()}

    app.mount("/assets", StaticFiles(directory=ROOT / "web/workspace"), name="workspace-assets")
    return app
