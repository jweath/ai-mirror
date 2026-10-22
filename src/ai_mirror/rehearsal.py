"""One explicit instructor-only transport rehearsal, outside the class outbox."""
import threading

from .slack import SlackError
from .store import now_iso
from .workflow import EXIT_PROMPT

LOCK = threading.Lock()


def send_rehearsal(store, settings, slack):
    course = store.course()
    channel = settings.rehearsal_channel_id
    if not course or not channel:
        raise ValueError("Configure the private instructor rehearsal channel first")
    if channel in {p.channel_id for p in course.projects}:
        raise ValueError("The rehearsal cannot target a student project channel")
    with LOCK:
        existing = store.get("instructor_rehearsal")
        if existing:
            return existing
        identity = slack.call("auth.test", {})
        info = slack.call("conversations.info", {"channel": channel}).get("channel", {})
        members = slack.call("conversations.members", {"channel": channel, "limit": 100})
        allowed = set(course.instructor_slack_ids) | {identity.get("user_id")}
        if (identity.get("team_id") != course.workspace_id or not info.get("is_private")
                or not info.get("is_member") or info.get("is_archived")
                or members.get("response_metadata", {}).get("next_cursor")
                or set(members.get("members", [])) != allowed or len(allowed) != 2):
            raise ValueError("Rehearsal requires a private channel containing only John and the AI Mirror bot")
        state = {"channel": channel, "status": "delivering", "started_at": now_iso()}
        store.set("instructor_rehearsal", state)
        try:
            receipt = slack.post({"channel": channel,
                                  "text": "*Private instructor rehearsal — no class messages enabled*\n\n" + EXIT_PROMPT})
        except SlackError as exc:
            state.update(status="uncertain" if exc.uncertain else "failed", detail=exc.code)
            store.set("instructor_rehearsal", state)
            raise
        state.update(status="sent", prompt_ts=receipt["ts"])
        store.set("instructor_rehearsal", state)
        store.audit("instructor_rehearsal", {"channel": channel, "provider_ts": receipt["ts"]})
        return state


def capture_rehearsal(store, payload):
    state, course = store.get("instructor_rehearsal"), store.course()
    event = payload.get("event", {})
    if (not state or not course or payload.get("team_id") != course.workspace_id
            or event.get("type") != "message" or event.get("subtype") or event.get("bot_id")
            or event.get("channel") != state["channel"] or not state.get("prompt_ts")
            or event.get("thread_ts") != state["prompt_ts"]
            or event.get("user") not in course.instructor_slack_ids or not event.get("text")):
        return
    state.update(status="reply_captured", reply_ts=event.get("ts"), captured_at=now_iso())
    # Verify delivery and capture without retaining the rehearsal's message text.
    store.set("instructor_rehearsal", state)
