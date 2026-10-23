from __future__ import annotations

import base64
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

from .github_app import credentials
from .workflow import parse_submission


class GitHub:
    def __init__(self, token="", transport=None, app_id="", private_key="", repositories=()):
        self.app_id, self.private_key = app_id, private_key
        self.repositories = {r.lower() for r in repositories if r}
        self.tokens = {}
        self.client = httpx.Client(base_url="https://api.github.com", timeout=20, transport=transport,
                                   headers={"Accept": "application/vnd.github+json",
                                            "X-GitHub-Api-Version": "2022-11-28",
                                            **({"Authorization": f"Bearer {token}"} if token else {})})

    @classmethod
    def configured(cls, settings, course=None):
        config = credentials(settings) or {}
        return cls(settings.github_token if not config else "", app_id=str(config.get("id", "")),
                   private_key=config.get("pem", ""),
                   repositories=[p.repository for p in course.projects] if course else [])

    def request(self, path, params=None):
        if bool(self.app_id) != bool(self.private_key):
            return httpx.Response(503, json={"message": "Incomplete App configuration"})
        if not self.app_id:
            return self.client.get(path, params=params)
        match = re.match(r"^/repos/([^/]+/[^/]+)/", path)
        repository = match[1] if match else ""
        if repository.lower() not in self.repositories:
            return httpx.Response(403, json={"message": "Repository is outside the configured course"})
        cached = self.tokens.get(repository.lower())
        if not cached or cached[1] < time.time() + 300:
            now = int(time.time())
            key = RSAKey.import_key(self.private_key)
            assertion = jwt.encode({"alg": "RS256"}, {"iat": now - 60, "exp": now + 540, "iss": self.app_id}, key)
            headers = {"Authorization": "Bearer " + assertion}
            installation = self.client.get(f"/repos/{repository}/installation", headers=headers)
            if installation.status_code == 404:
                # A public repository remains readable without an installation.
                # An explicit empty header prevents falling back to a personal token.
                return self.client.get(path, params=params, headers={"Authorization": ""})
            if installation.status_code != 200:
                return installation
            installation_id = installation.json().get("id")
            if not isinstance(installation_id, int):
                return httpx.Response(502, json={})
            response = self.client.post(f"/app/installations/{installation_id}/access_tokens", headers=headers,
                                        json={"repositories": [repository.split("/")[1]],
                                              "permissions": {"contents": "read", "issues": "read"}})
            if response.status_code != 201:
                return response
            data = response.json()
            if not data.get("token") or not data.get("expires_at"):
                return httpx.Response(502, json={})
            cached = (data["token"], datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp())
            self.tokens[repository.lower()] = cached
        response = self.client.get(path, params=params, headers={"Authorization": "Bearer " + cached[0]})
        if response.status_code in (401, 403):
            self.tokens.pop(repository.lower(), None)
        return response

    def close(self):
        self.client.close()

    def pages(self, path, params=None):
        items = []
        for page in range(1, 6):
            try:
                response = self.request(path, params={**(params or {}), "per_page": 100, "page": page})
            except (httpx.HTTPError, ValueError, JoseError):
                return items, "GitHub could not be reached; collection incomplete"
            if response.status_code != 200:
                return items, f"GitHub HTTP {response.status_code}; collection incomplete"
            try:
                rows = response.json()
            except ValueError:
                return items, "Unexpected GitHub response; collection incomplete"
            if not isinstance(rows, list):
                return items, "Unexpected GitHub response; collection incomplete"
            items.extend(rows)
            if len(rows) < 100:
                return items, None
        return items, "Stopped at 500 records; collection may be incomplete"

    def journal(self, source):
        path = quote(source["path"], safe="/")
        try:
            result = self.request(f"/repos/{source['repository']}/contents/{path}", params={"ref": source["sha"]})
        except (httpx.HTTPError, ValueError, JoseError):
            return None, "Journal connection or App configuration unavailable"
        if result.status_code != 200:
            return None, f"Journal HTTP {result.status_code}; contents unavailable"
        value = result.json()
        if value.get("type") != "file" or value.get("encoding") != "base64" or value.get("size", 0) > 100_000:
            return None, "Journal must be a Markdown file under 100 KB"
        try:
            return base64.b64decode(value["content"]).decode("utf-8"), None
        except (ValueError, KeyError, UnicodeDecodeError):
            return None, "Journal content could not be decoded"


def collect_github(store, github, now=None, project_ids=None):
    course = store.course()
    if not course or not course.github_enabled:
        return {"status": "disabled", "warnings": []}
    now = now or datetime.now(timezone.utc)
    # A bounded rolling evidence window, disclosed in each snapshot, not a sprint total.
    since = (now - timedelta(days=14)).isoformat()
    warnings = []
    for project in course.projects:
        if project_ids is not None and project.id not in project_ids:
            continue
        if not project.repository:
            message = "Repository link has not been verified"
            warnings.append(f"{project.id}: {message}")
            store.set(f"project_evidence/{course.sprint}/{project.id}",
                      {"collected_at": now.isoformat(), "since": since, "items": [],
                       "warnings": [message], "complete": False})
            continue
        project_warnings = []
        commits, error = github.pages(f"/repos/{project.repository}/commits", {"since": since})
        if error:
            warnings.append(f"{project.id}: {error}")
            project_warnings.append(error)
        issues, error = github.pages(f"/repos/{project.repository}/issues", {"since": since, "state": "all"})
        if error:
            warnings.append(f"{project.id}: {error}")
            project_warnings.append(error)
        # Repository activity stays at project level, including unlinked authors.
        # It is evidence of changes, never a student effort/learning score.
        project_items = [{"type": "commit", "url": c.get("html_url"), "sha": c.get("sha"),
                          "text": c.get("commit", {}).get("message", "")[:500],
                          "at": c.get("commit", {}).get("committer", {}).get("date"),
                          "author": (c.get("author") or {}).get("login")}
                         for c in commits]
        project_items += [{"type": "pull_request" if "pull_request" in i else "issue",
                           "url": i.get("html_url"), "text": i.get("title", "")[:500],
                           "state": i.get("state"), "at": i.get("updated_at"),
                           "author": (i.get("user") or {}).get("login")}
                          for i in issues]
        project_items.sort(key=lambda item: item["at"] or "", reverse=True)
        if len(project_items) > 100:
            project_warnings.append("Limited to 100 recent project items")
        store.set(f"project_evidence/{course.sprint}/{project.id}",
                  {"collected_at": now.isoformat(), "since": since, "items": project_items[:100],
                   "warnings": project_warnings, "complete": not project_warnings})
        members = [s for s in course.students if s.project_id == project.id]
        for student in members:
            if not student.github_login:
                continue
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
                titles = {f"Learning journal: {name} — {course.sprint}".casefold()
                          for name in (student.id, student.name)}
                if ("pull_request" not in issue and issue.get("state") == "closed"
                        and issue.get("title", "").casefold() in titles
                        and issue.get("user", {}).get("login", "").lower() == student.github_login.lower()):
                    bodies = [issue.get("body") or ""]
                    if issue.get("comments", 0):
                        comments, comment_error = github.pages(
                            f"/repos/{project.repository}/issues/{issue['number']}/comments")
                        if comment_error:
                            warnings.append(f"{student.id}: submission comments incomplete")
                        bodies += [c.get("body") or "" for c in comments
                                   if c.get("user", {}).get("login", "").lower() == student.github_login.lower()]
                    for body in bodies:
                        links = re.findall(r"https://github\.com/[^\s<>)]+/blob/[a-fA-F0-9]{40}/[^\s<>)]+\.md", body)
                        # The convention identifies the human file, never an arbitrary AI brief.
                        link = next((url for url in links if url.endswith("/reflection.md")), None)
                        if link:
                            try:
                                source = parse_submission(link, project.repository)
                            except ValueError:
                                continue
                            source["issue_url"] = issue.get("html_url")
                            store.add_entry(f"submission/github/{student.id}/{issue['number']}/{source['sha']}",
                                            student.id, course.sprint, "submission", "Closed submission issue", source)
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
    if project_ids is None:
        store.set("last_github_collection", {"at": now.isoformat(), "warnings": warnings})
    return {"status": "collected", "warnings": warnings}
