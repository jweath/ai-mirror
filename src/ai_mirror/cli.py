from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import ROOT, Course, Settings
from .store import Store
from .workflow import peer_rotation, plan


def api(method, path, data=None):
    settings = Settings.from_env()
    if len(settings.admin_token) < 32:
        raise ValueError("Set MIRROR_ADMIN_TOKEN in your environment; do not put it in command arguments")
    response = httpx.request(method, settings.public_url + path, json=data, timeout=120,
                             headers={"Authorization": f"Bearer {settings.admin_token}"})
    if response.status_code >= 400:
        raise ValueError(f"Service HTTP {response.status_code}: {response.json().get('detail', 'Request failed')}")
    return response.json()


def safe_id(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError("Use a lowercase student/sprint identifier containing letters, numbers, - or _")
    return value


def new_journal(student, sprint, destination):
    directory = Path(destination) / "journal" / safe_id(student) / safe_id(sprint)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "reflection.md"
    text = f"""# {student} · {sprint} learning journal

AI starting point: <!-- Link the dated AI brief you actually saw. -->

## Original goals and test thresholds
<!-- Write your own goals and decision thresholds here. -->

## Dated changes to the plan

## Hypothesis → Build → Measure → Learn

## My AI/technical learning and verification

## Learning check
Question:
My answer:

## Muddiest point and next step

## Feedback I used or questioned

## Next goal

## Evidence and AI use
"""
    # Never overwrite an existing reflection on resume.
    with path.open("x") as file:
        file.write(text)
    return path


def submission_body(repo, student, sprint, sha, journal, brief, peer):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Repository must be owner/name")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Use a full commit SHA")
    path = Path(journal)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".md":
        raise ValueError("Journal must be a relative Markdown path within the repository")
    if not brief.startswith("https://"):
        raise ValueError("Supply the stable AI starting-point URL")
    return (f"Journal: https://github.com/{repo}/blob/{sha}/{path.as_posix()}\n\n"
            f"AI starting point: {brief}\n\nPeer feedback: {peer or 'Pending; add the thread link when available.'}\n\n"
            f"Student: {student}\nSprint: {sprint}\n\n"
            "Closing this issue records submission, not a grade or a finding of authorship.\n")


def main():
    parser = argparse.ArgumentParser(description="AI Mirror: student artifacts and instructor operations")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-course", help="Validate roster IDs, project mappings, and explicit dates")
    validate.add_argument("file")
    preview = sub.add_parser("preview", help="Preview upcoming sends without contacting Slack")
    preview.add_argument("file")
    peers = sub.add_parser("peers", help="Preview a deterministic partner-free peer rotation")
    peers.add_argument("file")
    peers.add_argument("--round", default="midpoint")
    init = sub.add_parser("new", help="Create a blank human-authored journal; never overwrite existing work")
    init.add_argument("--student", required=True)
    init.add_argument("--sprint", default="sprint-3")
    init.add_argument("--destination", default=".")
    install = sub.add_parser("student-file", help="Copy the single portable skill")
    install.add_argument("destination")
    manifest = sub.add_parser("slack-manifest", help="Render the Slack app manifest for your service URL")
    manifest.add_argument("--url", required=True)
    upload = sub.add_parser("configure", help="Upload an already-reviewed course config to the service")
    upload.add_argument("file")
    for name in ("status", "collect", "digest", "hold"):
        sub.add_parser(name)
    backup = sub.add_parser("backup", help="Consistent local database backup; includes private records")
    backup.add_argument("destination")
    restore = sub.add_parser("restore", help="Restore offline with all sends held; never overwrite a database")
    restore.add_argument("source")
    restore.add_argument("destination")
    submit = sub.add_parser("submission", help="Preview a GitHub submission issue, or publish and close it")
    for field in ("repo", "student", "sprint", "sha", "journal", "brief"):
        submit.add_argument("--" + field, required=True)
    submit.add_argument("--peer")
    submit.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    try:
        if args.command in ("validate-course", "preview", "peers", "configure"):
            course = Course.model_validate_json(Path(args.file).read_text())
            if args.command == "validate-course":
                result = {"valid": True, "students": len(course.students), "projects": len(course.projects),
                          "active": course.active, "meetings": len(course.meetings)}
            elif args.command == "preview":
                result = plan(course, datetime.now(timezone.utc))
            elif args.command == "peers":
                result = peer_rotation(course, args.round)
            else:
                result = api("PUT", "/api/course", course.model_dump(mode="json"))
        elif args.command == "new":
            result = {"created": str(new_journal(args.student, args.sprint, args.destination)),
                      "next": "Give the portable skill to your assistant; you write the reflection."}
        elif args.command == "student-file":
            with Path(args.destination).open("x") as file:
                file.write((ROOT / "skills/ai-mirror/SKILL.md").read_text())
            result = {"created": args.destination}
        elif args.command == "slack-manifest":
            if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?", args.url):
                raise ValueError("Use your HTTPS service origin, with no path or token")
            result = json.loads((ROOT / "config/slack-manifest.json").read_text().replace(
                "https://YOUR-SERVICE.up.railway.app", args.url))
        elif args.command == "status":
            result = api("GET", "/api/status")
        elif args.command in ("collect", "digest", "hold"):
            endpoint = "digests" if args.command == "digest" else args.command
            result = api("POST", "/api/" + endpoint)
        elif args.command == "backup":
            if Path(args.destination).exists():
                raise ValueError("Backup target exists; choose a new file")
            Store(Settings.from_env().db_path).backup(args.destination)
            result = {"backup": args.destination, "private": True}
        elif args.command == "restore":
            if Path(args.destination).exists():
                raise ValueError("Restore target exists; stop the service and choose a fresh path")
            # Source must be a consistent backup, not a live file copied without its WAL.
            shutil.copyfile(args.source, args.destination)
            restored = Store(args.destination)
            restored.set("delivery_hold", True)
            with restored.connect() as db:
                db.execute("UPDATE outbox SET status='uncertain' WHERE status IN ('pending','delivering')")
            restored.audit("restored_under_hold", {})
            result = {"restored": args.destination, "delivery_hold": True,
                      "next": "Reconcile provider history, then explicitly release the hold."}
        elif args.command == "submission":
            body = submission_body(args.repo, args.student, args.sprint, args.sha, args.journal, args.brief, args.peer)
            if not args.publish:
                result = {"title": f"Learning journal: {args.student} — {args.sprint}", "body": body, "published": False}
            else:
                # Verify the exact file is accessible before creating a receipt. gh uses the student's own account.
                subprocess.run(["gh", "api", f"repos/{args.repo}/contents/{args.journal}?ref={args.sha}"],
                               check=True, stdout=subprocess.DEVNULL)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".md") as file:
                    file.write(body)
                    file.flush()
                    issue = subprocess.check_output(["gh", "issue", "create", "--repo", args.repo, "--title",
                                                      f"Learning journal: {args.student} — {args.sprint}",
                                                      "--body-file", file.name], text=True).strip()
                # Print the receipt immediately so a close failure can be recovered without creating a duplicate.
                print(json.dumps({"created_issue": issue, "next": "Closing submission receipt"}))
                subprocess.run(["gh", "issue", "close", issue, "--reason", "completed"], check=True)
                result = {"issue": issue, "submitted": True}
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        # Do not print provider request objects or environment values.
        parser.exit(1, f"AI Mirror: {exc}\n")


if __name__ == "__main__":
    main()
