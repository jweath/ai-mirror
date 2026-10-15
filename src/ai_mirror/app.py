from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import ROOT, Course, Settings, StrictModel
from .digest import generate
from .evidence import GitHub, collect_github
from .slack import Slack, SlackError, plain_slack, verify_signature
from .store import Store, content_hash, now_iso
from .workflow import deliver_one, enqueue_due, handle_command, handle_event, plan

logger = logging.getLogger("ai_mirror")


class Approval(StrictModel):
    digest_id: str
    student_id: str
    draft_hash: str
    text: str = Field(min_length=1, max_length=2500)
    reviewed: bool


class Reconcile(StrictModel):
    action: str
    reason: str = Field(min_length=10, max_length=500)
    provider_ts: str | None = None


def tick(store, settings, slack):
    enqueue_due(store)
    for _ in range(50):
        if deliver_one(store, settings, slack) is None:
            break
    course = store.course()
    if not course:
        return
    now = datetime.now(timezone.utc)
    last = store.get("last_github_collection", {}).get("at")
    if course.active and course.github_enabled and (not last or datetime.fromisoformat(last) < now - timedelta(hours=6)):
        github = GitHub(settings.github_token)
        try:
            collect_github(store, github, now)
        finally:
            github.close()
    for meeting in course.meetings:
        key = f"daily_digest/{course.sprint}/{meeting.id}"
        if (course.active and meeting.kind == "exit_ticket" and course.activated_at
                and meeting.at >= course.activated_at
                and timedelta(minutes=30) <= now - meeting.at <= timedelta(hours=12)
                and not store.get(key)):
            last_attempt = store.get(key + "/attempt")
            if not last_attempt or datetime.fromisoformat(last_attempt) < now - timedelta(hours=1):
                store.set(key + "/attempt", now.isoformat())
                result = generate(store, settings)
                store.set(key, result["id"])
    cutoff = (now - timedelta(days=course.retention_days)).isoformat()
    store.purge(cutoff)


def create_app(settings=None, store=None, slack=None):
    settings = settings or Settings.from_env()
    store = store or Store(settings.db_path)
    slack = slack or Slack(settings.slack_token)

    @asynccontextmanager
    async def lifespan(app):
        store.recover()

        async def loop():
            while True:
                try:
                    await run_in_threadpool(tick, store, settings, slack)
                except Exception:
                    # Source text, tokens, and provider response bodies never enter service logs.
                    logger.warning("Background task incomplete; inspect authenticated status and provider access")
                await asyncio.sleep(30)

        task = asyncio.create_task(loop()) if settings.background_enabled else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="AI Mirror", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.settings = settings

    @app.middleware("http")
    async def headers_and_size(request, call_next):
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid body length"}, status_code=400)
        if size > 1_000_000:
            return JSONResponse({"detail": "Body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def admin(request: Request):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if len(settings.admin_token) < 32 or not hmac.compare_digest(token, settings.admin_token):
            raise HTTPException(401, "Instructor authentication required")

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(SlackError)
    async def slack_error(request, exc):
        return JSONResponse({"detail": exc.code}, status_code=502)

    @app.get("/healthz")
    def health():
        store.get("health_probe")
        return {"status": "ok", "version": __version__}

    @app.get("/")
    def home():
        return FileResponse(ROOT / "web/index.html")

    @app.get("/instructor")
    def instructor():
        return FileResponse(ROOT / "web/instructor.html")

    @app.get("/skill.md")
    def skill():
        return FileResponse(ROOT / "skills/ai-mirror/SKILL.md", media_type="text/markdown",
                            filename="ai-mirror.md")

    @app.get("/assignment.md")
    def assignment():
        return FileResponse(ROOT / "docs/assignment.md", media_type="text/markdown")

    @app.get("/api/status", dependencies=[Depends(admin)])
    def status():
        course = store.course()
        requirements = []
        if not course:
            requirements.append("Import the verified course roster and project/channel mappings")
        elif not course.meetings:
            requirements.append("Set explicit class exit-ticket and peer-review dates/times")
        if not settings.slack_token:
            requirements.append("Set SLACK_BOT_TOKEN from the AI Mirror Slack app")
        if not settings.slack_signing_secret:
            requirements.append("Set SLACK_SIGNING_SECRET and configure Slack endpoints")
        if course and not course.active:
            requirements.append("Review the schedule preview and activate the course")
        if not settings.sends_enabled:
            requirements.append("Enable MIRROR_SEND_ENABLED after the preview is correct")
        if store.get("delivery_hold", False):
            requirements.append("Resolve the delivery hold before any sends")
        return {"version": __version__, "course": course.model_dump(mode="json") if course else None,
                "sends_enabled": settings.sends_enabled, "delivery_hold": store.get("delivery_hold", False),
                "requirements": requirements, "digest_provider": settings.digest_provider,
                "github": store.get("last_github_collection"), "digests": store.digest_list(),
                "outbox": store.outbox()}

    @app.put("/api/course", dependencies=[Depends(admin)])
    def save_course(course: Course):
        if course.active:
            if not settings.slack_token or not settings.slack_signing_secret:
                raise ValueError("Connect Slack before activating; an inactive course can be saved now")
            identity = slack.call("auth.test", {})
            if identity.get("team_id") != course.workspace_id:
                raise ValueError("Slack token belongs to another workspace")
            for project in course.projects:
                info = slack.call("conversations.info", {"channel": project.channel_id}).get("channel", {})
                if not info.get("is_member") or info.get("is_archived"):
                    raise ValueError(f"Invite AI Mirror to the active project channel for {project.id} before activating")
        store.save_course(course)
        return {"saved": True, "active": course.active}

    @app.get("/api/preview", dependencies=[Depends(admin)])
    def preview():
        course = store.course()
        return {"jobs": plan(course, datetime.now(timezone.utc), store.get("previous_peer_pairs", []),
                             store.get(f"peer_rotations/{course.sprint}", {})) if course else []}

    @app.get("/api/entries", dependencies=[Depends(admin)])
    def entries():
        course = store.course()
        return {"entries": store.entries(course.sprint) if course else []}

    @app.post("/api/collect", dependencies=[Depends(admin)])
    def collect():
        github = GitHub(settings.github_token)
        try:
            return collect_github(store, github)
        finally:
            github.close()

    @app.post("/api/digests", dependencies=[Depends(admin)])
    def digest():
        return generate(store, settings)

    @app.get("/api/digests/{id}", dependencies=[Depends(admin)])
    def get_digest(id: str):
        value = store.digest(id)
        if not value:
            raise HTTPException(404, "Digest not found")
        value["body"]["students"] = [{**row, "draft_hash": content_hash(row)} for row in value["body"]["students"]]
        return value

    @app.post("/api/feedback", dependencies=[Depends(admin)])
    def feedback(approval: Approval):
        course = store.course()
        digest = store.digest(approval.digest_id)
        if not course or not digest or digest["sprint"] != course.sprint:
            raise ValueError("Digest must belong to the current sprint")
        row = next((r for r in digest["body"]["students"] if r["student_id"] == approval.student_id), None)
        if not row or approval.draft_hash != content_hash(row) or not approval.reviewed:
            raise ValueError("Review the current digest and explicitly approve the feedback")
        student = next(s for s in course.students if s.id == approval.student_id)
        if not approval.text.strip():
            raise ValueError("Feedback cannot be blank")
        payload = {"channel": course.project(student).channel_id, "sprint": course.sprint,
                   "text": f"<@{student.slack_id}> *Instructor feedback*\n{plain_slack(approval.text)}"}
        id = f"feedback/{approval.digest_id}/{student.id}"
        store.enqueue(id, "feedback", payload, now_iso())
        store.audit("feedback_approved", {"id": id, "draft_hash": approval.draft_hash,
                                         "approved_hash": content_hash(approval.text)})
        return {"queued": True, "id": id, "destination": payload["channel"],
                "notice": "Reviewed feedback is visible in the student's project channel; global send gates still apply."}

    @app.post("/api/hold", dependencies=[Depends(admin)])
    def hold():
        store.set("delivery_hold", True)
        store.audit("delivery_hold", {})
        return {"held": True}

    @app.post("/api/release-hold", dependencies=[Depends(admin)])
    def release_hold(body: Reconcile):
        if body.action != "release_hold":
            raise ValueError("Explicit release_hold action required after reconciling provider history")
        if any(r["status"] in ("uncertain", "delivering") for r in store.outbox()):
            raise ValueError("Reconcile uncertain/in-flight deliveries before releasing the hold")
        store.audit("hold_released", {"reason": body.reason})
        store.set("delivery_hold", False)
        return {"held": False}

    @app.post("/api/outbox/{id:path}/reconcile", dependencies=[Depends(admin)])
    def reconcile(id: str, body: Reconcile):
        row = next((r for r in store.outbox() if r["id"] == id), None)
        if not row or row["status"] not in ("uncertain", "failed", "pending"):
            raise ValueError("Only pending, failed, or uncertain deliveries can be reconciled")
        if body.action == "cancel":
            store.finish(id, "cancelled", detail=body.reason)
        elif body.action == "retry_confirmed_unsent":
            # Operator must inspect the provider before attesting that no message was delivered.
            store.finish(id, "pending", detail=body.reason)
        elif body.action == "mark_sent" and body.provider_ts:
            store.finish(id, "sent", body.provider_ts, body.reason)
            if row["kind"] == "exit_ticket":
                p = row["payload"]
                store.add_prompt(p["channel"], body.provider_ts, p["meeting_id"], p["sprint"])
        else:
            raise ValueError("Use cancel, retry_confirmed_unsent, or mark_sent with provider_ts after inspection")
        store.audit("delivery_reconciled", {"id": id, **body.model_dump()})
        return {"reconciled": True}

    async def signed_body(request):
        raw = await request.body()
        if len(raw) > 1_000_000:
            raise HTTPException(413, "Body too large")
        if not verify_signature(settings.slack_signing_secret, raw,
                                request.headers.get("x-slack-request-timestamp", ""),
                                request.headers.get("x-slack-signature", "")):
            raise HTTPException(401, "Invalid Slack signature")
        return raw

    @app.post("/slack/events")
    async def events(request: Request):
        import json
        raw = await signed_body(request)
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Invalid JSON") from None
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        handle_event(store, payload)
        return {"ok": True}

    @app.post("/slack/commands")
    async def commands(request: Request):
        raw = await signed_body(request)
        form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        if not form.get("trigger_id"):
            raise HTTPException(400, "Missing Slack request identity")
        return handle_command(store, form)

    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
    return app


app = create_app()
