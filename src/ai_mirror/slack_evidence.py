"""Read only the registered owners' updates in their registered project rooms."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .slack import SlackError, slack_link


def capture(store, course, message, channel):
    student = course.student_by_slack(message.get("user"))
    if (not student or course.project(student).channel_id != channel
            or message.get("bot_id") or message.get("subtype")
            or not message.get("ts") or not message.get("text", "").strip()):
        return False
    store.add_entry(f"project-slack/{channel}/{message['ts']}", student.id, course.sprint,
                    "project_update", message["text"][:12000],
                    {"url": slack_link(course.workspace_id, channel, message["ts"],
                                       store.get("slack_workspace_url")),
                     "channel": channel, "ts": message["ts"], "thread_ts": message.get("thread_ts"),
                     "at": datetime.fromtimestamp(float(message["ts"]), timezone.utc).isoformat()})
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
        return
    if event.get("subtype") == "message_changed":
        event = event.get("message", {})
    capture(store, course, event, channel)


def collect_slack(store, slack, now=None):
    course = store.course()
    if not course or not course.slack_enabled:
        return {"status": "disabled", "warnings": []}
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=14)
    warnings = []
    identity = slack.call("auth.test", {})
    if identity.get("team_id") != course.workspace_id:
        raise SlackError("wrong_workspace")
    if identity.get("url"):
        store.set("slack_workspace_url", identity["url"])
    for project in course.projects:
        warning, cursor = None, None
        seen = set()
        try:
            for _ in range(5):
                result = slack.call("conversations.history", {
                    "channel": project.channel_id, "oldest": str(since.timestamp()), "limit": 100,
                    **({"cursor": cursor} if cursor else {})})
                for message in result.get("messages", []):
                    if capture(store, course, message, project.channel_id):
                        seen.add(f"project-slack/{project.channel_id}/{message['ts']}")
                cursor = result.get("response_metadata", {}).get("next_cursor")
                if not cursor and not result.get("has_more"):
                    break
                if not cursor:
                    warning = "Slack pagination incomplete"
                    break
            else:
                warning = "Stopped at 500 messages; history incomplete"
        except SlackError as exc:
            warning = "Slack collection unavailable: " + exc.code
        if warning:
            warnings.append(f"{project.id}: {warning}")
        else:
            # History excludes thread replies. Reconcile top-level records only,
            # after a complete read; signed events handle edits/deletes in threads.
            with store.connect() as db:
                import json
                rows = db.execute("SELECT id,source FROM entries WHERE kind='project_update'").fetchall()
                for row in rows:
                    source = json.loads(row["source"])
                    if (source.get("channel") == project.channel_id and not source.get("thread_ts")
                            and float(source.get("ts", 0)) >= since.timestamp() and row["id"] not in seen):
                        db.execute("DELETE FROM entries WHERE id=?", (row["id"],))
        store.set(f"slack_collection/{project.id}",
                  {"at": now.isoformat(), "since": since.isoformat(), "complete": not warning,
                   "warning": warning})
    store.set("last_slack_collection", {"at": now.isoformat(), "warnings": warnings})
    return {"status": "collected", "warnings": warnings}
