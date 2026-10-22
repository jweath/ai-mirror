"""Course-only browser sessions. Slack verifies identity; the roster grants access."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from .config import ROOT
from .evidence import GitHub, collect_github
from .pinup import PinConflict, PinUpdate, board, save_pin
from .slack import SlackError

COOKIE = "__Secure-entr5000_session"
LIFETIME = 12 * 60 * 60


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_dashboard(settings, store, instructor_router=None, admin_dependency=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    public = urlsplit(settings.dashboard_url)
    prefix = public.path.rstrip("/")
    origin = f"{public.scheme}://{public.netloc}"
    configured = bool(settings.slack_client_id and settings.slack_client_secret
                      and len(settings.session_secret) >= 32 and public.scheme == "https")
    oauth = OAuth()
    if configured:
        oauth.register("slack", client_id=settings.slack_client_id,
                       client_secret=settings.slack_client_secret,
                       server_metadata_url="https://slack.com/.well-known/openid-configuration",
                       client_kwargs={"scope": "openid profile"})
        # Slack posts the callback across sites. This short-lived cookie holds
        # only signed OAuth state/nonce, never provider tokens or course records.
        app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                           session_cookie="__Secure-entr5000_oauth", max_age=600,
                           same_site="none", https_only=True, path=prefix + "/")
    app.state.oauth = oauth
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS browser_sessions (
            id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            csrf TEXT NOT NULL, expires REAL NOT NULL)""")

    def identity(user_id):
        if user_id == "admin/" + digest(settings.admin_token) and len(settings.admin_token) >= 32:
            return {"id": user_id, "name": "Instructor", "role": "instructor"}
        course = store.course()
        if not course:
            return None
        if user_id in course.instructor_slack_ids:
            return {"id": user_id, "name": "John", "role": "instructor"}
        student = course.student_by_slack(user_id)
        if student:
            return {"id": user_id, "name": student.name, "role": "student"}
        if user_id in course.viewer_slack_ids:
            return {"id": user_id, "name": "Course member", "role": "student"}
        return None

    def session(request: Request):
        sid = request.cookies.get(COOKIE, "")
        if not sid:
            raise HTTPException(401, "Sign in to open the course projects")
        with store.connect() as db:
            db.execute("DELETE FROM browser_sessions WHERE expires < ?", (time.time(),))
            row = db.execute("SELECT * FROM browser_sessions WHERE id_hash=? AND expires>?",
                             (digest(sid), time.time())).fetchone()
        user = identity(row["user_id"]) if row else None
        if not user:
            raise HTTPException(401, "Your course session has expired")
        if request.method not in ("GET", "HEAD"):
            if (request.headers.get("origin") != origin
                    or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"])):
                raise HTTPException(403, "Refresh the board before making this change")
        return {**user, "csrf": row["csrf"]}

    def instructor(user=Depends(session)):
        if user["role"] != "instructor":
            raise HTTPException(403, "Instructor access required")
        return user

    def issue(response, user_id, previous=""):
        sid, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute("DELETE FROM browser_sessions WHERE expires<? OR id_hash=?",
                       (time.time(), digest(previous)))
            db.execute("INSERT INTO browser_sessions VALUES (?,?,?,?)",
                       (digest(sid), user_id, csrf, time.time() + LIFETIME))
        response.set_cookie(COOKIE, sid, max_age=LIFETIME, secure=True, httponly=True,
                            samesite="lax", path=prefix + "/")
        return response

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/")
    def home():
        html = (ROOT / "web/pinup.html").read_text()
        html = html.replace('"/assets/', '"' + prefix + '/assets/')
        html = html.replace('<body class="pinup-page">',
                            f'<body class="pinup-page" data-course-base="{prefix}">')
        html = html.replace('/assets/pinup.js"', '/assets/course.js"')
        html = html.replace('Instructor preview', 'Course projects')
        html = html.replace('href="/instructor"', f'href="{prefix}/instructor"')
        html = html.replace('<h2>Open the project board</h2>',
                            f'<h2>Course projects</h2><a id="slack-login" class="product-link" '
                            f'href="{prefix}/auth/slack">Sign in with Slack</a>'
                            '<p id="login-help" class="fine"></p><details><summary>Instructor access</summary>')
        html = html.replace('</form></section>', '</form></details></section>', 1)
        html = html.replace('Your token stays in this tab’s memory.', 'Use the current instructor access token.')
        html = html.replace('Save private pin', 'Save project pin')
        html = html.replace('<p class="fine">Use one source',
                            '<label><input id="shared-pin" type="checkbox"> Show this pin to the class</label>'
                            '<p class="fine">Use one source')
        html = html.replace('This view is private; a course-site link does not publish its records.',
                            'Only the course roster can sign in. Instructor-only pins and private learning records '
                            'are excluded from the class view.')
        return HTMLResponse(html)

    @app.get("/api/session")
    def current(request: Request):
        try:
            user = session(request)
        except HTTPException:
            user = None
        return {"user": user, "slack_enabled": configured}

    @app.post("/api/admin-session")
    def admin_login(request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.headers.get("origin") != origin:
            raise HTTPException(403, "Open instructor access from the course site")
        if len(settings.admin_token) < 32 or not hmac.compare_digest(token, settings.admin_token):
            raise HTTPException(401, "Instructor authentication required")
        from fastapi.responses import JSONResponse
        return issue(JSONResponse({"signed_in": True}), "admin/" + digest(token),
                     request.cookies.get(COOKIE, ""))

    @app.get("/auth/slack")
    async def login(request: Request):
        course = store.course()
        if not configured or not course:
            return HTMLResponse("Slack sign-in is being connected. Please check back shortly.", status_code=503)
        request.session["instructor_return"] = request.query_params.get("next") == "instructor"
        return await oauth.slack.authorize_redirect(
            request, settings.dashboard_url + "/auth/callback", team=course.workspace_id,
            response_mode="form_post")

    @app.api_route("/auth/callback", methods=["GET", "POST"])
    async def callback(request: Request):
        if not configured:
            raise HTTPException(503, "Slack sign-in is not configured")
        try:
            # Authlib verifies the signature, issuer, audience, expiry and nonce,
            # and consumes the state bound to this browser's signed OAuth cookie.
            token = await oauth.slack.authorize_access_token(request)
            claims = token["userinfo"]
            course = store.course()
            user_id = claims.get("https://slack.com/user_id")
            if (not course or claims.get("https://slack.com/team_id") != course.workspace_id
                    or not identity(user_id)):
                raise ValueError("not_rostered")
        except Exception:
            request.session.clear()
            return HTMLResponse("Sign-in could not be completed for this course. Use your course Slack account.",
                                status_code=403)
        destination = "/instructor" if request.session.get("instructor_return") else "/"
        request.session.clear()
        return issue(RedirectResponse(settings.dashboard_url + destination, status_code=303), user_id,
                     request.cookies.get(COOKIE, ""))

    @app.post("/api/logout")
    def logout(request: Request, user=Depends(session)):
        from fastapi.responses import JSONResponse
        with store.connect() as db:
            db.execute("DELETE FROM browser_sessions WHERE id_hash=?",
                       (digest(request.cookies.get(COOKIE, "")),))
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(COOKIE, path=prefix + "/", secure=True, httponly=True, samesite="lax")
        return response

    @app.get("/api/board")
    def course_board(user=Depends(session)):
        return board(store, shared=user["role"] != "instructor")

    @app.put("/api/projects/{project_id}")
    def edit(project_id: str, update: PinUpdate, user=Depends(instructor)):
        try:
            return save_pin(store, project_id, update)
        except KeyError:
            raise HTTPException(404, "Project is not in this course") from None
        except PinConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/collect")
    async def collect(user=Depends(instructor)):
        github = GitHub.configured(settings, store.course())
        try:
            return await run_in_threadpool(collect_github, store, github)
        finally:
            github.close()

    @app.get("/instructor")
    def instructor_workspace(request: Request):
        try:
            user = session(request)
        except HTTPException:
            return RedirectResponse(prefix + "/auth/slack?next=instructor", status_code=303)
        if user["role"] != "instructor":
            raise HTTPException(403, "Instructor access required")
        html = (ROOT / "web/instructor.html").read_text()
        html = html.replace('"/assets/', '"' + prefix + '/assets/')
        html = html.replace('<body class="pinup-page">', f'<body class="pinup-page" data-instructor-base="{prefix}">')
        html = html.replace('href="/pinup"', f'href="{prefix}/"')
        html = html.replace('href="/"', 'href="/entr/"')
        return HTMLResponse(html)

    if instructor_router is not None:
        # Reuse the same API handlers with roster-based authorization and CSRF
        # checks. The legacy operator API retains its bearer-token dependency.
        app.dependency_overrides[admin_dependency] = instructor
        app.include_router(instructor_router, prefix="/instructor")

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(SlackError)
    async def slack_error(request, exc):
        return JSONResponse({"detail": exc.code}, status_code=502)

    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="course-assets")
    return app
