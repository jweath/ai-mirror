"""Read-only learning projection from the existing participation bot.

The bridge credential cannot access participation grades or mutate attendance.
Course grants and exact Slack IDs are checked before releasing any projection.
"""

import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx


def photo_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        return (
            value
            if (
                parsed.scheme == "https"
                and not parsed.username
                and not parsed.password
                and parsed.port in (None, 443)
                and (host.endswith(".slack-edge.com") or host == "secure.gravatar.com")
            )
            else ""
        )
    except ValueError:
        return ""


class LearningClient:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.transport = None
        self.lock = threading.Lock()
        self.checked = None
        self.error = None

    def snapshot(self, force=False):
        now = datetime.now(timezone.utc)
        with self.lock:
            if self.settings.learning_token and (
                force or not self.checked or now - self.checked > timedelta(seconds=60)
            ):
                try:
                    with httpx.Client(transport=self.transport, timeout=8, follow_redirects=False) as client:
                        response = client.get(
                            self.settings.learning_url,
                            headers={"Authorization": "Bearer " + self.settings.learning_token},
                        )
                    response.raise_for_status()
                    if len(response.content) > 4_000_000:
                        raise ValueError("Learning source too large")
                    data = response.json()
                    if not isinstance(data.get("assignments"), list) or not isinstance(
                        data.get("profiles"), dict
                    ):
                        raise ValueError("Invalid learning source")
                    self.store.set("learning_snapshot", data)
                    self.store.set(
                        "learning_profiles",
                        {
                            sid: photo_url(p.get("url"))
                            for sid, p in data["profiles"].items()
                            if isinstance(p, dict)
                        },
                    )
                    self.error = None
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    self.error = "The participation bot could not be reached. Showing the last saved read."
                self.checked = now
            data = deepcopy(self.store.get("learning_snapshot", {}))
        data["connected"] = bool(self.settings.learning_token and not self.error and data.get("checked_at"))
        data["error"] = self.error or (
            None if self.settings.learning_token else "The participation connection is not configured."
        )
        return data


def people_with_photos(store, members):
    profiles = store.get("learning_profiles", {})
    return [
        {"name": m.name, "slack_id": m.slack_id, "photo": photo_url(profiles.get(m.slack_id, ""))}
        for m in members
    ]


TOPICS = [
    ("Customer understanding", ("usability", "customer", "consumer", "testing", "user research")),
    ("Pricing and revenue", ("revenue", "paying", "price", "pricing", "freemium", "business version")),
    ("Focus and simplicity", ("simple", "simplicity", "complex", "features", "focus")),
    ("Growth and distribution", ("referral", "marketing", "growth", "distribution", "acquisition")),
    ("Founder decisions", ("founder", "partnership", "cofounder", "co-founder", "team")),
]


def project_learning(snapshot, directory, user, instructor=False):
    """Filter every record against today's explicit directory grants."""
    allowed = {
        g["section"]
        for g in user["grants"]
        if g["course"] == "5500" and (not instructor or g["role"] == "instructor")
    }
    roster = directory.snapshot({"5500"})
    names = {p["slack_id"]: p["name"] for p in roster["people"]}
    enrolled = {
        (p["slack_id"], e["section"])
        for p in roster["people"]
        for e in p["enrollments"]
        if e["course"] == "5500"
    }
    result = {
        "connected": snapshot.get("connected", False),
        "error": snapshot.get("error"),
        "checked_at": snapshot.get("checked_at"),
        "assignments": [],
        "reflections": [],
    }
    for assignment in snapshot.get("assignments", []):
        sections = []
        for source in assignment["sections"]:
            section = source["id"].removeprefix("26f-5500-jw-")
            if section not in allowed:
                continue
            students = []
            for person in source["students"]:
                sid = person["slack_id"]
                if (sid, section) not in enrolled or (not instructor and sid != user["id"]):
                    continue
                students.append({**person, "name": names.get(sid, "Student")})
            item = {**source, "id": section, "students": students}
            if not instructor:
                item.pop("channels", None)
            else:
                posts = [{**s["response"], "slack_id": s["slack_id"]} for s in students if s["response"]]
                item["topics"] = [
                    {
                        "title": title,
                        "slack_ids": [
                            p["slack_id"] for p in posts if any(term in p["text"].lower() for term in terms)
                        ],
                    }
                    for title, terms in TOPICS
                ]
                item["topics"] = [t for t in item["topics"] if t["slack_ids"]]
            sections.append(item)
        if sections:
            result["assignments"].append({**assignment, "sections": sections})
    for source in snapshot.get("reflections", []):
        section = source["section"].removeprefix("26f-5500-jw-")
        sid = source["slack_id"]
        if section in allowed and (sid, section) in enrolled and (instructor or sid == user["id"]):
            result["reflections"].append({**source, "section": section, "name": names.get(sid, "Student")})
    return result
