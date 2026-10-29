import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from test_dashboard import ORIGIN, PREFIX, seed_session
from test_dashboard import dashboard as dashboard  # pytest fixture registration

from ai_mirror.app import create_app
from ai_mirror.pinup import PinConflict, board
from ai_mirror.showcase import Media, ProfileUpdate, ProjectProfile, save_profile


def profile(**kw):
    return ProjectProfile(name="Garden", sources=[{"url": "https://example.com/slack"}], **kw)


def png():
    out = io.BytesIO()
    Image.new("RGB", (40, 40), "green").save(out, "PNG")
    return out.getvalue()


def test_course_scope_revision_visibility_and_validation(store, course):
    saved = save_profile(store, "garden", ProfileUpdate(profile=profile()))
    assert board(store)["projects"][0]["showcase"]["name"] == "Garden"
    assert board(store, shared=True)["projects"][0]["showcase"] is None
    with pytest.raises(PinConflict):
        save_profile(store, "garden", ProfileUpdate(profile=profile()))
    save_profile(
        store, "garden", ProfileUpdate(profile=profile(shared=True), expected_revision=saved["revision"])
    )
    assert board(store, shared=True)["projects"][0]["showcase"]["name"] == "Garden"
    course.sprint = "sprint-4"
    store.save_course(course)
    assert board(store, shared=True)["projects"][0]["showcase"]["name"] == "Garden"
    course.id = "another-offering"
    with pytest.raises(ValueError, match="one offering"):
        store.save_course(course)
    for kw in [{"live_url": "javascript:alert(1)"}, {"features": ["a"] * 6}, {"screenshots": [{}] * 6}]:
        with pytest.raises(ValidationError):
            profile(**kw)
    with pytest.raises(ValidationError):
        ProjectProfile(name="No source")


def test_media_and_writes_keep_roster_auth_and_csrf(dashboard, store, course):
    client, _ = dashboard
    path = PREFIX + "/api/projects/garden"
    assert client.get(path + "/media/" + "0" * 64).status_code == 401
    seed_session(client, store, course.students[0].slack_id)
    headers = {"Origin": ORIGIN, "X-CSRF-Token": "csrf-value"}
    assert client.post(path + "/media", content=png(), headers=headers).status_code == 403
    assert client.put(path + "/profile", json={"profile": {}}, headers=headers).status_code == 403
    seed_session(client, store, course.instructor_slack_ids[0])
    assert client.post(path + "/media", content=png()).status_code == 403
    upload = client.post(path + "/media", content=png(), headers=headers)
    assert upload.status_code == 200
    asset = Media(
        asset_id=upload.json()["asset_id"], alt="Demo screenshot", source_url="https://example.com/slack"
    )
    media = path + "/media/" + asset.asset_id
    response = client.get(media)
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.post(path + "/media", content=b'<svg onload="alert(1)">', headers=headers).status_code == 400
    )
    assert (
        client.post(path + "/media", content=b"x" * (5 * 1024 * 1024 + 1), headers=headers).status_code == 413
    )
    saved = save_profile(store, "garden", ProfileUpdate(profile=profile(screenshots=[asset])))
    seed_session(client, store, course.students[0].slack_id)
    assert client.get(media).status_code == 404
    save_profile(
        store,
        "garden",
        ProfileUpdate(profile=profile(shared=True, screenshots=[asset]), expected_revision=saved["revision"]),
    )
    assert client.get(media).status_code == 200
    # Another project cannot borrow the image, even within the same class.
    with pytest.raises(ValueError):
        save_profile(store, course.projects[1].id, ProfileUpdate(profile=profile(screenshots=[asset])))
    course.students = course.students[1:]
    store.save_course(course)
    assert client.get(media).status_code in (401, 403)


def test_operator_api_and_retention(settings, store, slack):
    with TestClient(create_app(settings, store, slack)) as client:
        path = "/api/showcase/projects/garden"
        assert client.put(path, json={"profile": {}}).status_code == 401
        headers = {"Authorization": "Bearer " + settings.admin_token}
        data = {"profile": profile(shared=True).model_dump(mode="json")}
        assert client.put(path, json=data, headers=headers).status_code == 200
        assert client.put(path, json=data, headers=headers).status_code == 409
        assert (
            client.put("/api/showcase/projects/not-on-roster", json=data, headers=headers).status_code == 404
        )
    store.purge("2099-01-01T00:00:00+00:00")
    assert board(store)["projects"][0]["showcase"] is None
