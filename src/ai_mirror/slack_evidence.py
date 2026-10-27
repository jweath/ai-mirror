"""Read only the registered owners' updates in their registered project rooms."""
from __future__ import annotations

import html
import json
import re
import threading
from datetime import datetime, timedelta, timezone

from .slack import SlackError, slack_link

COLLECTION_LOCK = threading.Lock()


def capture_github(store, course, message, channel):
    project = next((p for p in course.projects if p.channel_id == channel), None)
    if (not project or not project.repository or not course.github_slack_app_id
            or message.get("app_id") != course.github_slack_app_id
            or not message.get("bot_id") or not message.get("ts")):
        return False
    try:
        posted = datetime.fromtimestamp(float(message["ts"]), timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return False
    items = []
    for number, attachment in enumerate(message.get("attachments", [])):
        title = attachment.get("title") or attachment.get("fallback") or ""
        if re.match(r"^(?:Subscribed|Unsubscribed|Sign in|Connected|Welcome)\b", title, re.I):
            continue
        urls = re.findall(r"https://github\.com/[^\s<>|]+", title + " " + (attachment.get("title_link") or ""))
        expected = "https://github.com/" + project.repository.lower()
        if not any(url.lower() == expected or url.lower().startswith(expected + "/") for url in urls):
            continue
        # Only notification titles/links enter the projection, never attachment
        # bodies (which can contain journal text or private issue descriptions).
        label = html.unescape(re.sub(r"<[^>|]+\|([^>]+)>", r"\1", title))[:400]
        items.append({"id": f"{message['ts']}/{number}", "ts": message["ts"],
                      "type": "github_notification", "text": label,
                      "thread_ts": message.get("thread_ts"),
                      "github_url": next(url for url in urls if url.lower().startswith(expected + "/"))
                      if any(url.lower().startswith(expected + "/") for url in urls) else expected,
                      "event": re.sub(r" by .*", "", (attachment.get("fallback") or "").split("] ")[-1])[:100],
                      "url": slack_link(course.workspace_id, channel, message["ts"],
                                        store.get("slack_workspace_url")),
                      "at": posted.isoformat(),
                      "author": "GitHub via Slack"})
    if not items:
        return False
    key = f"github_notifications/{course.sprint}/{project.id}"
    cutoff = (datetime.now(timezone.utc) - timedelta(days=course.retention_days)).isoformat()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        previous = json.loads(row["value"]) if row else {}
        combined = {item["id"]: item for item in previous.get("items", []) + items if item["at"] >= cutoff}
        value = {"collected_at": datetime.now(timezone.utc).isoformat(),
                 "items": sorted(combined.values(), key=lambda i: i["at"], reverse=True)[:200]}
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
    return True


def capture(store, course, message, channel):
    student = course.student_by_slack(message.get("user"))
    if (not student or course.project(student).channel_id != channel
            or message.get("bot_id") or message.get("subtype") not in (None, "thread_broadcast")
            or not message.get("ts") or not message.get("text", "").strip()
            or message["text"].lstrip().startswith("/")):
        return False
    try:
        posted = datetime.fromtimestamp(float(message["ts"]), timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return False
    store.add_entry(f"project-slack/{channel}/{message['ts']}", student.id, course.sprint,
                    "project_update", message["text"][:12000],
                    {"url": slack_link(course.workspace_id, channel, message["ts"],
                                       store.get("slack_workspace_url")),
                     "channel": channel, "ts": message["ts"], "thread_ts": message.get("thread_ts"),
                     "at": posted})
    with store.connect() as db:
        db.execute("UPDATE entries SET created_at=? WHERE id=?",
                   (posted, f"project-slack/{channel}/{message['ts']}"))
    return True


def project_event(store, payload):
    course = store.course()
    if not course or not course.slack_enabled or payload.get("team_id") != course.workspace_id:
        return
    event = payload.get("event", {})
    channel = event.get("channel")
    if event.get("type") != "message" or channel not in {p.channel_id for p in course.projects}:
        return
    if event.get("subtype") == "message_deleted":
        with store.connect() as db:
            db.execute("DELETE FROM entries WHERE id=?", (f"project-slack/{channel}/{event.get('deleted_ts')}",))
            project = next(p for p in course.projects if p.channel_id == channel)
            key = f"github_notifications/{course.sprint}/{project.id}"
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row:
                value = json.loads(row["value"])
                value["items"] = [i for i in value.get("items", []) if i["ts"] != event.get("deleted_ts")]
                db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(value), key))
        return
    if event.get("subtype") == "message_changed":
        event = event.get("message", {})
        # Withdraw the previous projection before applying a replacement, even
        # when the replacement no longer qualifies as a project update.
        project_event(store, {"team_id": course.workspace_id, "event": {
            "type": "message", "subtype": "message_deleted", "channel": channel,
            "deleted_ts": event.get("ts")}})
    capture(store, course, event, channel)
    capture_github(store, course, event, channel)


def collect_slack(store, slack, now=None, project_ids=None):
    if not COLLECTION_LOCK.acquire(blocking=False):
        return {"status": "busy", "warnings": []}
    try:
        return _collect_slack(store, slack, now, project_ids)
    finally:
        COLLECTION_LOCK.release()


def _collect_slack(store, slack, now=None, project_ids=None):
    course = store.course()
    if not course or not course.slack_enabled:
        return {"status": "disabled", "warnings": []}
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=course.retention_days)
    warnings = []
    identity = slack.call("auth.test", {})
    if identity.get("team_id") != course.workspace_id:
        raise SlackError("wrong_workspace")
    if identity.get("url"):
        store.set("slack_workspace_url", identity["url"])
    for project in course.projects:
        if project_ids is not None and project.id not in project_ids:
            continue
        warning, cursor = None, None
        seen, message_ids, parents = set(), set(), []
        history_complete = False
        try:
            for _ in range(5):
                result = slack.call("conversations.history", {
                    "channel": project.channel_id, "oldest": str(since.timestamp()), "limit": 100,
                    **({"cursor": cursor} if cursor else {})})
                for message in result.get("messages", []):
                    message_ids.add(message.get("ts"))
                    if message.get("reply_count"):
                        parents.append(message)
                    capture_github(store, course, message, project.channel_id)
                    if capture(store, course, message, project.channel_id):
                        seen.add(f"project-slack/{project.channel_id}/{message['ts']}")
                cursor = result.get("response_metadata", {}).get("next_cursor")
                if not cursor and not result.get("has_more"):
                    history_complete = True
                    break
                if not cursor:
                    warning = "Slack pagination incomplete"
                    break
            else:
                warning = "Stopped at 500 messages; history incomplete"
        except SlackError as exc:
            warning = "Slack collection unavailable: " + exc.code
        # Read thread replies using the existing history scopes. Cache completed
        # threads by Slack's latest reply marker, so quiet threads aren't fetched
        # repeatedly. Signed events continue to handle edits and deletions.
        thread_key = f"slack_threads/{course.sprint}/{project.id}"
        checked_threads = store.get(thread_key, {})
        if len(parents) > 25:
            warning = warning or "Stopped at 25 threads; older thread history is incomplete"
        for parent in parents[:25]:
            marker = [parent.get("reply_count"), parent.get("latest_reply")]
            if checked_threads.get(parent["ts"]) == marker:
                continue
            thread_cursor = None
            try:
                for _ in range(2):
                    result = slack.call("conversations.replies", {
                        "channel": project.channel_id, "ts": parent["ts"], "limit": 100,
                        **({"cursor": thread_cursor} if thread_cursor else {})})
                    for message in result.get("messages", []):
                        if float(message.get("ts", 0)) < since.timestamp():
                            continue
                        capture_github(store, course, message, project.channel_id)
                        capture(store, course, message, project.channel_id)
                    thread_cursor = result.get("response_metadata", {}).get("next_cursor")
                    if not thread_cursor and not result.get("has_more"):
                        checked_threads[parent["ts"]] = marker
                        break
                    if not thread_cursor:
                        warning = warning or "Thread pagination incomplete"
                        break
                else:
                    warning = warning or "Stopped at 200 replies; thread history is incomplete"
            except SlackError as exc:
                warning = warning or "Thread collection unavailable: " + exc.code
                if exc.code in ("rate_limited", "missing_scope", "not_allowed_token_type"):
                    break
        store.set(thread_key, {ts: marker for ts, marker in checked_threads.items()
                               if float(ts) >= since.timestamp()})
        if warning:
            warnings.append(f"{project.id}: {warning}")
        else:
            # Reconcile top-level records only after a complete read. Thread
            # edits/deletions arrive through signed events.
            with store.connect() as db:
                rows = db.execute("SELECT id,source FROM entries WHERE kind='project_update'").fetchall()
                for row in rows:
                    source = json.loads(row["source"])
                    if (source.get("channel") == project.channel_id and not source.get("thread_ts")
                            and since.timestamp() <= float(source.get("ts", 0)) < now.timestamp()
                            and row["id"] not in seen):
                        db.execute("DELETE FROM entries WHERE id=?", (row["id"],))
        key = f"github_notifications/{course.sprint}/{project.id}"
        saved = store.get(key, {})
        saved["items"] = [item for item in saved.get("items", []) if item["at"] >= since.isoformat()
                          and (not history_complete or item["at"] >= now.isoformat() or item.get("thread_ts")
                               or item["ts"] in message_ids)]
        store.set(key, saved)
        store.set(f"slack_collection/{project.id}",
                  {"at": now.isoformat(), "since": since.isoformat(), "complete": not warning,
                   "history_complete": history_complete, "warning": warning})
    if project_ids is None:
        store.set("last_slack_collection", {"at": now.isoformat(), "warnings": warnings})
    return {"status": "collected", "warnings": warnings}
