from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx


class GitHub:
    def __init__(self, token="", transport=None):
        self.client = httpx.Client(base_url="https://api.github.com", timeout=20, transport=transport,
                                   headers={"Accept": "application/vnd.github+json",
                                            "X-GitHub-Api-Version": "2022-11-28",
                                            **({"Authorization": f"Bearer {token}"} if token else {})})

    def close(self):
        self.client.close()

    def pages(self, path, params=None):
        items = []
        for page in range(1, 6):
            response = self.client.get(path, params={**(params or {}), "per_page": 100, "page": page})
            if response.status_code != 200:
                return items, f"GitHub HTTP {response.status_code}; collection incomplete"
            rows = response.json()
            if not isinstance(rows, list):
                return items, "Unexpected GitHub response; collection incomplete"
            items.extend(rows)
            if len(rows) < 100:
                return items, None
        return items, "Stopped at 500 records; collection may be incomplete"

    def journal(self, source):
        path = quote(source["path"], safe="/")
        result = self.client.get(f"/repos/{source['repository']}/contents/{path}", params={"ref": source["sha"]})
        if result.status_code != 200:
            return None, f"Journal HTTP {result.status_code}; contents unavailable"
        value = result.json()
        if value.get("type") != "file" or value.get("encoding") != "base64" or value.get("size", 0) > 100_000:
            return None, "Journal must be a Markdown file under 100 KB"
        try:
            return base64.b64decode(value["content"]).decode("utf-8"), None
        except (ValueError, KeyError, UnicodeDecodeError):
            return None, "Journal content could not be decoded"


def collect_github(store, github, now=None):
    course = store.course()
    if not course or not course.github_enabled:
        return {"status": "disabled", "warnings": []}
    now = now or datetime.now(timezone.utc)
    # A bounded rolling evidence window, disclosed in each snapshot, not a sprint total.
    since = (now - timedelta(days=14)).isoformat()
    warnings = []
    for project in course.projects:
        commits, error = github.pages(f"/repos/{project.repository}/commits", {"since": since})
        if error:
            warnings.append(f"{project.id}: {error}")
        issues, error = github.pages(f"/repos/{project.repository}/issues", {"since": since, "state": "all"})
        if error:
            warnings.append(f"{project.id}: {error}")
        members = [s for s in course.students if s.project_id == project.id]
        for student in members:
            evidence = []
            for commit in commits:
                login = (commit.get("author") or {}).get("login", "")
                # Do not assign all shared-repo work to both owners or infer authorship from display names.
                if login.lower() == student.github_login.lower():
                    evidence.append({"type": "commit", "url": commit.get("html_url"),
                                     "text": commit.get("commit", {}).get("message", "")[:500],
                                     "sha": commit.get("sha"), "attribution": "GitHub author account; verify human contribution"})
            for issue in issues:
                involved = [issue.get("user", {}).get("login", "")]
                involved += [a.get("login", "") for a in issue.get("assignees", [])]
                if student.github_login.lower() in [x.lower() for x in involved]:
                    evidence.append({"type": "pull_request" if "pull_request" in issue else "issue",
                                     "url": issue.get("html_url"), "text": issue.get("title", "")[:500],
                                     "state": issue.get("state"), "attribution": "author or assignee; not proof work occurred"})
            store.set(f"evidence/{course.sprint}/{student.id}",
                      {"collected_at": now.isoformat(), "since": since, "items": evidence[:100],
                       "warnings": [w for w in warnings if w.startswith(project.id + ":")]
                       + (["Limited to 100 student evidence items"] if len(evidence) > 100 else [])})
            submissions = [e for e in store.entries(course.sprint, student.id) if e["kind"] == "submission"]
            if submissions:
                submission = submissions[0]
                text, error = github.journal(submission["source"])
                if error:
                    warnings.append(f"{student.id}: {error}")
                elif text is not None:
                    store.add_entry("journal/" + submission["id"], student.id, course.sprint, "journal",
                                    text, submission["source"])
    store.set("last_github_collection", {"at": now.isoformat(), "warnings": warnings})
    return {"status": "collected", "warnings": warnings}
