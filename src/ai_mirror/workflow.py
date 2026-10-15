from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .config import Course
from .slack import SlackError, plain_slack, slack_link

EXIT_PROMPT = (
    "*AI Mirror · exit ticket*\n"
    "Each project owner: reply in this thread in your own words (about 2–3 sentences).\n"
    "1. What changed in your project or thinking today?\n"
    "2. What evidence supports that? Link it when possible.\n"
    "3. What is still muddy, and what will you try next?\n"
    "‘I'm still unsure’ is useful. AI may gather evidence; you write the reflection. "
    "Use `/mirror muddy …` for a private note to the instructor."
)


def peer_rotation(course: Course, round_id: str, previous=None):
    """One incoming/outgoing review; never self or project partner. Stable per round."""
    students = sorted(course.students, key=lambda s: s.id)
    previous = set(tuple(x) for x in (previous or []))
    rng = random.Random(f"{course.id}/{course.sprint}/{round_id}")
    best, score = None, len(students) + 1
    for _ in range(3000):
        recipients = list(students)
        rng.shuffle(recipients)
        if any(a.project_id == b.project_id for a, b in zip(students, recipients)):
            continue
        pairs = [(a.id, b.id) for a, b in zip(students, recipients)]
        repeats = sum(pair in previous for pair in pairs)
        if repeats < score:
            best, score = pairs, repeats
        if score == 0:
            break
    if best is None:
        raise ValueError("No partner-free rotation fits this roster; instructor must arrange external/group feedback")
    return best


def plan(course: Course, now: datetime, previous=None, rotations=None):
    """Only upcoming/current explicit meetings. Never invent dates or backfill old prompts."""
    jobs = []
    for meeting in sorted(course.meetings, key=lambda m: m.at):
        at = meeting.at.astimezone(timezone.utc)
        if at < now - timedelta(minutes=15):
            continue
        if course.activated_at and at < course.activated_at:
            continue
        if meeting.kind == "exit_ticket":
            for project in course.projects:
                owners = [s for s in course.students if s.project_id == project.id]
                if not owners:
                    continue
                jobs.append({"id": f"{course.id}/{course.sprint}/{meeting.id}/{project.id}",
                             "kind": "exit_ticket", "due_at": at.isoformat(),
                             "payload": {"channel": project.channel_id,
                                         "text": " ".join(f"<@{s.slack_id}>" for s in owners) + "\n" + EXIT_PROMPT,
                                         "meeting_id": meeting.id, "sprint": course.sprint}})
        else:
            pairs = (rotations or {}).get(meeting.id) or peer_rotation(course, meeting.id, previous)
            previous = pairs
            for reviewer_id, author_id in pairs:
                reviewer = next(s for s in course.students if s.id == reviewer_id)
                author = next(s for s in course.students if s.id == author_id)
                jobs.append({"id": f"{course.id}/{course.sprint}/{meeting.id}/{reviewer.id}",
                             "kind": "peer_review", "due_at": at.isoformat(),
                             "payload": {"channel": course.project(reviewer).channel_id,
                                         "text": f"<@{reviewer.slack_id}> Your reflection partner this round is "
                                                 f"<@{author.slack_id}> in <#{course.project(author).channel_id}>. "
                                                 "Read their journal post, then reply in its thread with one "
                                                 "specific strength linked to their goal, one question about "
                                                 "their evidence, and one small next test. Write it yourself. "
                                                 "If their post is missing, ask for it; do not invent a review. "
                                                 "Authors: reply with what you will use or question.",
                                         "meeting_id": meeting.id, "sprint": course.sprint,
                                         "reviewer_id": reviewer.id, "author_id": author.id}})
    return jobs


def enqueue_due(store, now=None):
    now = now or datetime.now(timezone.utc)
    course = store.course()
    if not course or not course.active or store.get("delivery_hold", False):
        return 0
    count = 0
    cache_key = f"peer_rotations/{course.sprint}"
    rotations = store.get(cache_key, {})
    jobs = plan(course, now, store.get("previous_peer_pairs", []), rotations)
    for job in jobs:
        if datetime.fromisoformat(job["due_at"]) <= now:
            count += store.enqueue(job["id"], job["kind"], job["payload"], job["due_at"])
            if job["kind"] == "peer_review":
                round_id = job["payload"]["meeting_id"]
                if round_id not in rotations:
                    pairs = [(j["payload"]["reviewer_id"], j["payload"]["author_id"])
                             for j in jobs if j["kind"] == "peer_review" and j["payload"]["meeting_id"] == round_id]
                    rotations[round_id] = pairs
                    store.set(cache_key, rotations)
                    store.set("previous_peer_pairs", pairs)
    return count


def deliver_one(store, settings, slack, now=None):
    now = now or datetime.now(timezone.utc)
    course = store.course()
    if not (settings.sends_enabled and course and course.active) or store.get("delivery_hold", False):
        return None
    job = store.claim(now.isoformat())
    if not job:
        return None
    payload = job["payload"]
    channels = {p.channel_id for p in course.projects}
    if payload.get("channel") not in channels or payload.get("sprint") != course.sprint:
        store.finish(job["id"], "cancelled", detail="Scope changed; review before sending")
        return "cancelled"
    if job["kind"] in ("exit_ticket", "peer_review") and (
        datetime.fromisoformat(job["due_at"]) < now - timedelta(minutes=15)
        or datetime.fromisoformat(job["due_at"]) < course.activated_at
    ):
        store.finish(job["id"], "expired", detail="No late reminder backfill")
        return "expired"
    try:
        receipt = slack.post(payload)
    except SlackError as exc:
        # Even a rejected send needs deliberate retry; no duplicate-send loop.
        status = "uncertain" if exc.uncertain else "failed"
        store.finish(job["id"], status, detail=exc.code)
        return status
    store.finish(job["id"], "sent", receipt["ts"])
    if job["kind"] == "exit_ticket":
        store.add_prompt(payload["channel"], receipt["ts"], payload["meeting_id"], payload["sprint"])
    store.audit("message_sent", {"id": job["id"], "ts": receipt["ts"], "kind": job["kind"]})
    return "sent"


def handle_event(store, payload):
    course = store.course()
    if not course or payload.get("team_id") != course.workspace_id:
        return "ignored"
    event = payload.get("event", {})
    if event.get("type") != "message" or event.get("bot_id"):
        return "ignored"
    if event.get("subtype") == "message_deleted":
        deleted_ts = event.get("deleted_ts")
        with store.connect() as db:
            db.execute("DELETE FROM entries WHERE id=?", (f"slack/{event.get('channel')}/{deleted_ts}",))
        return "deleted"
    if event.get("subtype") == "message_changed":
        event = {**event.get("message", {}), "channel": event.get("channel")}
    elif event.get("subtype"):
        return "ignored"
    student = course.student_by_slack(event.get("user"))
    if not student or event.get("channel") != course.project(student).channel_id:
        return "ignored"
    prompt = store.prompt(event.get("channel"), event.get("thread_ts"))
    if not prompt or not event.get("ts"):
        return "ignored"
    store.add_entry(f"slack/{event['channel']}/{event['ts']}", student.id, prompt["sprint"], "exit_ticket",
                    event.get("text", "")[:12000],
                    {"url": slack_link(course.workspace_id, event["channel"], event["ts"],
                                       store.get("slack_workspace_url")),
                     "channel": event["channel"], "ts": event["ts"], "thread_ts": event["thread_ts"]})
    return "recorded"


def parse_submission(text, repository):
    parts = text.split()
    if not parts:
        raise ValueError("Supply a GitHub file URL pinned to a full 40-character commit SHA")
    url = urlparse(parts[0])
    pattern = rf"/{re.escape(repository)}/blob/([a-fA-F0-9]{{40}})/(.+\.md)"
    match = re.fullmatch(pattern, url.path)
    if url.scheme != "https" or url.netloc != "github.com" or not match or url.query or url.fragment:
        raise ValueError("Use your registered repository's Markdown file link with a full commit SHA, not main")
    if any(part in ("..", ".") for part in match[2].split("/")) or "%" in match[2]:
        raise ValueError("Invalid journal path")
    issue = None
    if len(parts) > 1:
        issue = parts[1]
        if not re.fullmatch(rf"https://github.com/{re.escape(repository)}/issues/[1-9][0-9]*", issue):
            raise ValueError("Issue must belong to the same project repository")
    if len(parts) > 2:
        raise ValueError("Supply the journal URL and optionally its submission issue URL")
    return {"url": parts[0], "repository": repository, "sha": match[1], "path": match[2], "issue_url": issue}


def handle_command(store, form):
    course = store.course()
    if not course or form.get("team_id") != course.workspace_id:
        return {"response_type": "ephemeral", "text": "AI Mirror is not configured for this workspace yet."}
    student = course.student_by_slack(form.get("user_id"))
    if not student:
        return {"response_type": "ephemeral", "text": "Your Slack ID is not in this course roster. Ask John to map it."}
    command, _, text = form.get("text", "").partition(" ")
    result = {"response_type": "ephemeral"}
    source = {"channel": form.get("channel_id"), "via": "slash_command"}
    # Slack's trigger_id stays the same on transport retries; hash without saving raw credentials/body.
    import hashlib
    id = "command/" + hashlib.sha256(form.get("trigger_id", "").encode()).hexdigest()
    with store.connect() as db:
        if db.execute("SELECT 1 FROM entries WHERE id=?", (id,)).fetchone():
            return {"response_type": "ephemeral", "text": "This entry is already recorded; no duplicate was posted."}
    if command in ("exit", "submit") and form.get("channel_id") != course.project(student).channel_id:
        result["text"] = "Run this in your registered project channel so classmates can see your work."
        return result
    if command in ("exit", "muddy"):
        if not text.strip() or len(text) > 12000:
            result["text"] = "Add your own short reflection after the command (maximum 12,000 characters)."
        else:
            private = command == "muddy"
            store.add_entry(id, student.id, course.sprint, "muddiest_point" if private else "exit_ticket",
                            text, source, private)
            result["response_type"] = "ephemeral" if private else "in_channel"
            result["text"] = ("Saved privately for the instructor. It is not an AI score." if private
                              else f"*{plain_slack(student.name)} · exit ticket*\n{plain_slack(text)}")
    elif command == "submit":
        try:
            source = parse_submission(text, course.project(student).repository)
            store.add_entry(id, student.id, course.sprint, "submission", "Submitted journal link", source)
            result["text"] = "Recorded your exact journal version. Post your human-written reflection in this channel for peers."
        except ValueError as exc:
            result["text"] = str(exc)
    elif command == "status":
        entries = store.entries(course.sprint, student.id)
        result["text"] = (f"{course.sprint}: {len(entries)} captured entries; "
                          f"journal link {'recorded' if any(e['kind'] == 'submission' for e in entries) else 'not yet recorded'}. "
                          "This is a receipt, not a grade or an effort score.")
    else:
        result["text"] = ("Reply to an AI Mirror exit-ticket thread, or use `/mirror exit your reflection` in your project "
                          "channel. `/mirror muddy your uncertainty` is private to the instructor. "
                          "`/mirror submit COMMIT_FILE_URL ISSUE_URL` records a journal. `/mirror status` shows receipts. "
                          "Write reflections yourself; AI may gather evidence and ask questions.")
    return result
