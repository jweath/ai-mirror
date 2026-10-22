import time
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from ai_mirror.dashboard import COOKIE, create_dashboard, digest
from ai_mirror.pinup import PinUpdate, ProjectPin, save_pin

PREFIX = "/entr/5000/2026/fall"
ORIGIN = "https://jweath.com"


@pytest.fixture
def dashboard(settings, store):
    settings = replace(settings, session_secret="s" * 48, slack_client_id="client-id",
                       slack_client_secret="client-secret")
    app = create_dashboard(settings, store)
    outer = FastAPI()
    outer.mount(PREFIX, app)
    with TestClient(outer, base_url=ORIGIN, follow_redirects=False) as client:
        yield client, app


def seed_session(client, store, user_id):
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO browser_sessions VALUES (?,?,?,?)",
                   (digest("browser-secret"), user_id, "csrf-value", time.time() + 3600))
    client.cookies.set(COOKIE, "browser-secret", domain="jweath.com", path=PREFIX + "/")


def test_closed_by_default_and_no_cookie_credential_in_javascript(dashboard):
    client, _ = dashboard
    assert client.get(PREFIX + "/api/board").status_code == 401
    assert client.get(PREFIX + "/api/session").json()["user"] is None
    page = client.get(PREFIX + "/")
    assert page.status_code == 200
    assert PREFIX + "/assets/course.js" in page.text
    assert 'src="/assets/' not in page.text
    assert page.headers["cache-control"] == "no-store"
    assert client.get(PREFIX + "/auth/callback?code=forged&state=forged").status_code == 403


def test_students_cannot_read_instructor_pins_or_edit(dashboard, store, course):
    client, _ = dashboard
    student = course.students[0]
    save_pin(store, student.project_id, PinUpdate(pin=ProjectPin(
        goal="PRIVATE_COACHING", source_url="https://example.com/private")))
    store.add_entry("muddy", student.id, course.sprint, "muddiest_point", "PRIVATE_MUDDY", {}, True)
    store.add_entry("journal", student.id, course.sprint, "journal", "PRIVATE_JOURNAL", {})
    seed_session(client, store, student.slack_id)
    response = client.get(PREFIX + "/api/board")
    assert response.status_code == 200
    assert "PRIVATE_" not in response.text
    assert client.put(PREFIX + "/api/projects/" + student.project_id,
                      headers={"Origin": ORIGIN, "X-CSRF-Token": "csrf-value"}, json={"pin": {}}).status_code == 403
    course.students = course.students[1:]
    store.save_course(course)
    assert client.get(PREFIX + "/api/board").status_code == 401


def test_session_cookie_logout_csrf_and_rotation(dashboard, settings, store):
    client, _ = dashboard
    auth = {"Authorization": "Bearer " + settings.admin_token, "Origin": ORIGIN}
    assert client.post(PREFIX + "/api/admin-session", headers={**auth, "Origin": "https://evil.test"}).status_code == 403
    login = client.post(PREFIX + "/api/admin-session", headers=auth)
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "Path=" + PREFIX + "/" in cookie
    user = client.get(PREFIX + "/api/session").json()["user"]
    assert user["role"] == "instructor"
    assert client.post(PREFIX + "/api/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert client.post(PREFIX + "/api/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": user["csrf"]}).status_code == 200
    assert client.get(PREFIX + "/api/board").status_code == 401
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM browser_sessions").fetchone()[0] == 0


def oidc_provider(app, course, mutation=None):
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    auth_nonce = {}
    def provider(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": "https://slack.com", "authorization_endpoint": "https://slack.com/openid/connect/authorize",
                "token_endpoint": "https://slack.com/api/openid.connect.token",
                "jwks_uri": "https://slack.com/openid/connect/keys", "response_types_supported": ["code"],
                "id_token_signing_alg_values_supported": ["RS256"]})
        if request.url.path == "/openid/connect/keys":
            return httpx.Response(200, json={"keys": [key.as_dict(private=False)]})
        if request.url.path == "/api/openid.connect.token":
            claims = {"iss": "https://slack.com", "aud": "client-id", "sub": "slack-subject",
                      "iat": int(time.time()), "exp": int(time.time()) + 600, "nonce": auth_nonce["nonce"],
                      "https://slack.com/team_id": course.workspace_id,
                      "https://slack.com/user_id": course.students[0].slack_id}
            claims.update(mutation or {})
            return httpx.Response(200, json={"access_token": "provider-token-never-stored", "token_type": "Bearer",
                                          "id_token": jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)})
        raise AssertionError(str(request.url))
    app.state.oauth.slack.client_kwargs["transport"] = httpx.MockTransport(provider)
    return auth_nonce


@pytest.mark.parametrize("mutation,expected", [
    ({}, 303), ({"aud": "another-app"}, 403), ({"iss": "https://evil.test"}, 403),
    ({"exp": 1}, 403), ({"nonce": "forged"}, 403),
    ({"https://slack.com/team_id": "TOTHER"}, 403),
    ({"https://slack.com/user_id": "USTRANGER"}, 403),
])
def test_real_oidc_signature_claims_state_nonce_and_roster(dashboard, course, mutation, expected):
    client, app = dashboard
    nonce = oidc_provider(app, course, mutation)
    start = client.get(PREFIX + "/auth/slack")
    assert start.status_code == 302
    params = parse_qs(urlsplit(start.headers["location"]).query)
    nonce["nonce"] = params["nonce"][0]
    assert params["team"] == [course.workspace_id]
    assert params["redirect_uri"] == [ORIGIN + PREFIX + "/auth/callback"]
    callback = client.post(PREFIX + "/auth/callback", data={"code": "provider-code", "state": params["state"][0]})
    assert callback.status_code == expected
    assert "provider-token-never-stored" not in str(client.cookies)
    assert client.get(PREFIX + "/api/board").status_code == (200 if expected == 303 else 401)


def test_callback_rejects_valid_code_from_another_browser(dashboard, course):
    client, app = dashboard
    nonce = oidc_provider(app, course)
    start = client.get(PREFIX + "/auth/slack")
    params = parse_qs(urlsplit(start.headers["location"]).query)
    nonce["nonce"] = params["nonce"][0]
    client.cookies.clear()
    assert client.post(PREFIX + "/auth/callback", data={"code": "valid-code", "state": params["state"][0]}).status_code == 403


def test_instructor_workspace_reuses_session_but_never_student_access(settings, store, course, slack):
    from ai_mirror.app import create_app
    full = create_app(settings, store, slack)
    dashboard = next(r.app for r in full.routes if getattr(r, "path", None) == "/course")
    outer = FastAPI()
    outer.mount(PREFIX, dashboard)
    store.add_entry("private", course.students[0].id, course.sprint, "muddiest_point", "PRIVATE_NOTE", {}, True)
    with TestClient(outer, base_url=ORIGIN, follow_redirects=False) as client:
        assert client.get(PREFIX + "/instructor").status_code == 303
        assert client.get(PREFIX + "/instructor/api/status").status_code == 401
        seed_session(client, store, course.students[0].slack_id)
        for path in ("/instructor", "/instructor/api/status", "/instructor/api/entries"):
            response = client.get(PREFIX + path)
            assert response.status_code == 403
            assert "PRIVATE_NOTE" not in response.text
        seed_session(client, store, course.instructor_slack_ids[0])
        page = client.get(PREFIX + "/instructor")
        assert page.status_code == 200 and f'data-instructor-base="{PREFIX}"' in page.text
        assert client.get(PREFIX + "/instructor/api/status").status_code == 200
        assert "PRIVATE_NOTE" in client.get(PREFIX + "/instructor/api/entries").text
        assert client.post(PREFIX + "/instructor/api/hold").status_code == 403
        headers = {"Origin": ORIGIN, "X-CSRF-Token": "csrf-value"}
        assert client.post(PREFIX + "/instructor/api/hold", headers=headers).status_code == 200
        assert client.get(PREFIX + "/instructor/api/status").headers["cache-control"] == "no-store"
        course.instructor_slack_ids = ["UOTHER"]
        store.save_course(course)
        assert client.get(PREFIX + "/instructor/api/entries").status_code == 401
    with TestClient(full) as legacy:
        assert legacy.get("/api/status").status_code == 401
        assert legacy.get("/api/status", headers={"Authorization": "Bearer " + settings.admin_token}).status_code == 200
