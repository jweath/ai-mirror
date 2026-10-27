"""Source-linked project activity, scoped to the roster and shared records."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from .slack import slack_link
from .store import content_hash


def at(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc).isoformat() if parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def notifications(store, course, project, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=course.retention_days)).isoformat()
    saved = store.get(f"github_notifications/{course.sprint}/{project.id}", {})
    items = [item for item in saved.get("items", []) if at(item.get("at")) and at(item["at"]) >= cutoff]
    return {**saved, "items": sorted(items, key=lambda item: at(item["at"]), reverse=True)[:200]}


def slack_status(store, course, project, now=None):
    now = now or datetime.now(timezone.utc)
    saved = store.get(f"slack_collection/{project.id}", {})
    items = notifications(store, course, project, now)["items"]
    checked = at(saved.get("at"))
    stale = not checked or checked < (now - timedelta(hours=48)).isoformat()
    return {"project_id": project.id, "project": project.name, "repository": project.repository,
            "channel_url": f"https://app.slack.com/client/{course.workspace_id}/{project.channel_id}",
            "channel_web_url": slack_link(course.workspace_id, project.channel_id, "1", store.get("slack_workspace_url")).removesuffix("/p1")
            if store.get("slack_workspace_url") else None,
            "checked_at": saved.get("at"), "complete": bool(saved.get("complete")),
            "history_complete": bool(saved.get("history_complete", saved.get("complete"))),
            "warning": saved.get("warning"), "stale": stale,
            "github_posts": len(items), "latest_github_at": items[0]["at"] if items else None,
            "latest_source_url": items[0]["url"] if items else None,
            "subscribe_command": f"/github subscribe {project.repository} issues pulls" if project.repository else None}


def project_activity(store, project, shared=False, now=None, entries=None):
    now = now or datetime.now(timezone.utc)
    course = store.course()
    cutoff = (now - timedelta(days=course.retention_days)).isoformat()
    owners = {s.id: s.name for s in course.students if s.project_id == project.id}
    events = []
    for entry in store.entries(course.sprint) if entries is None else entries:
        if (entry["student_id"] not in owners or entry["private"]
                or entry["kind"] not in ("exit_ticket", "project_update")
                or not entry["text"].strip() or entry["text"].lstrip().startswith("/")):
            continue
        source = entry["source"]
        when = at(source.get("at")) or at(entry["created_at"])
        if when and when >= cutoff:
            events.append({"id": "owner/" + entry["id"], "kind": "owner", "at": when,
                           "author": owners[entry["student_id"]], "title": "Project update",
                           "text": entry["text"], "url": source.get("url") or source.get("permalink")})
    for item in notifications(store, course, project, now)["items"]:
        events.append({"id": "github/" + item["id"], "kind": "github", "at": at(item["at"]),
                       "author": "GitHub via Slack", "title": item["text"], "text": "",
                       "event": item.get("event", "GitHub notification"), "url": item["url"],
                       "github_url": item.get("github_url")})
    current = store.get(f"pin/{course.sprint}/{project.id}")
    # Unsharing the current pin also withdraws its earlier snapshots from class view.
    if not shared or (current and current["pin"].get("shared")):
        with store.connect() as db:
            pins = [json.loads(r["value"]) for r in db.execute(
                "SELECT value FROM pin_history WHERE sprint=? AND project=?", (course.sprint, project.id))]
        if current and current not in pins:
            pins.append(current)
        for value in pins:
            pin = value["pin"]
            when = at(value["updated_at"])
            if (shared and not pin.get("shared")) or not when or when < cutoff:
                continue
            events.append({"id": "pin/" + content_hash(value), "kind": "pin", "at": when,
                           "title": "Project pin", "author": "Instructor",
                           "pin": pin, "url": pin.get("source_url"), "source_at": pin.get("source_at")})
    return sorted(events, key=lambda event: (event["at"], event["id"]), reverse=True)


def timeline(store, project, shared=False, cursor=None, limit=20, now=None):
    events = project_activity(store, project, shared, now)
    if cursor:
        try:
            boundary = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (not isinstance(boundary, list) or len(boundary) != 2
                    or not at(boundary[0]) or not isinstance(boundary[1], str)):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("Invalid timeline cursor") from None
        events = [event for event in events if (event["at"], event["id"]) < tuple(boundary)]
    page = events[:limit]
    next_cursor = (base64.urlsafe_b64encode(json.dumps([page[-1]["at"], page[-1]["id"]]).encode())
                   .decode().rstrip("=")) if len(events) > limit else None
    return {"events": page, "next_cursor": next_cursor}
