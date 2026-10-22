from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_mirror.app import create_app
from ai_mirror.evidence import GitHub, collect_github
from ai_mirror.pinup import PinConflict, PinUpdate, ProjectPin, board, save_pin


@pytest.fixture
def client(settings, store, slack):
    with TestClient(create_app(settings, store, slack)) as client:
        yield client


@pytest.fixture
def auth(settings):
    return {"Authorization": "Bearer " + settings.admin_token}


def test_board_shell_is_public_but_records_and_edits_require_auth(client):
    assert client.get("/pinup").status_code == 200
    assert client.get("/api/pinup").status_code == 401
    assert client.put("/api/pinup/projects/garden", json={"pin": {}}).status_code == 401


def test_board_keeps_private_notes_journals_and_digests_out(store, client, auth):
    store.add_entry("shared", "alex", "sprint-3", "exit_ticket", "Tested the signup", {})
    store.add_entry("private", "sam", "sprint-3", "muddiest_point", "PRIVATE_SECRET", {}, True)
    store.add_entry("journal", "sam", "sprint-3", "journal", "JOURNAL_SECRET", {})
    store.add_entry("old", "alex", "sprint-2", "exit_ticket", "OLD_SPRINT", {})
    store.save_digest("digest", "sprint-3", "extractive", {"private": "DIGEST_SECRET"})
    response = client.get("/api/pinup", headers=auth)
    assert response.headers["cache-control"] == "no-store"
    assert "Tested the signup" in response.text
    assert all(secret not in response.text for secret in ["PRIVATE_SECRET", "JOURNAL_SECRET", "OLD_SPRINT", "DIGEST_SECRET"])
    garden = next(p for p in response.json()["projects"] if p["id"] == "garden")
    assert {s["id"] for s in garden["owners"]} == {"alex", "sam"}
    assert garden["evidence_stale"] and garden["evidence"] is None
    assert garden["pin"]["goal"] == ""


def test_source_required_and_unsafe_links_rejected():
    with pytest.raises(ValidationError, match="source"):
        ProjectPin(goal="A stated goal")
    with pytest.raises(ValidationError, match="source"):
        ProjectPin(live_url="https://example.com")
    for url in ["javascript:alert(1)", "https://user:password@example.com", "http://example.com", "https://example.com/\nsecret"]:
        with pytest.raises(ValidationError):
            ProjectPin(source_url=url)
    with pytest.raises(ValidationError):
        ProjectPin(commitment_date="2026-10-29")


def test_pin_is_persistent_sprint_scoped_and_conflicting_edit_is_rejected(store, course, client, auth):
    update = {"pin": {"goal": "Someone can book a session", "source_url": "https://example.com/statement",
                      "source_kind": "student_statement"}}
    response = client.put("/api/pinup/projects/garden", headers=auth, json=update)
    assert response.status_code == 200
    assert board(store)["projects"][0]["pin"]["goal"] == "Someone can book a session"
    assert client.put("/api/pinup/projects/garden", headers=auth, json=update).status_code == 409
    update["expected_revision"] = response.json()["revision"]
    update["pin"]["goal"] = "Updated outcome"
    assert client.put("/api/pinup/projects/garden", headers=auth, json=update).status_code == 200
    assert client.put("/api/pinup/projects/other", headers=auth, json=update).status_code == 404
    course.sprint = "sprint-4"
    store.save_course(course)
    assert board(store)["projects"][0]["pin"]["goal"] == ""


def test_pin_freshness_uses_source_date_and_retention_clears_saved_text(store):
    now = datetime.now(timezone.utc)
    pin = ProjectPin(goal="Review the old goal", source_url="https://example.com/source",
                     source_at=now - timedelta(days=10))
    saved = save_pin(store, "garden", PinUpdate(pin=pin), now)
    assert board(store, now)["projects"][0]["pin_stale"]
    with pytest.raises(PinConflict):
        save_pin(store, "garden", PinUpdate(pin=pin, expected_revision="old"))
    assert saved["revision"]
    store.purge((now + timedelta(days=91)).isoformat())
    assert board(store)["projects"][0]["pin"]["goal"] == ""


def test_project_evidence_includes_unmapped_authors_and_discloses_failed_collection(store, course):
    course.github_enabled = True
    store.save_course(course)
    def handler(request):
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{"author": {"login": "outside-account"}, "sha": "a" * 40,
                "html_url": "https://github.com/example/garden/commit/" + "a" * 40,
                "commit": {"message": "An observed repository change", "committer": {"date": "2026-10-20T12:00:00Z"}}}])
        return httpx.Response(403, json={})
    github = GitHub(transport=httpx.MockTransport(handler))
    try:
        collect_github(store, github)
    finally:
        github.close()
    project = board(store)["projects"][0]
    assert not project["evidence"]["complete"] and project["evidence"]["warnings"]
    assert project["evidence"]["items"][0]["author"] == "outside-account"
    assert store.get("evidence/sprint-3/alex")["items"] == []
    assert store.get("evidence/sprint-3/sam")["items"] == []
    later = datetime.now(timezone.utc) + timedelta(days=3)
    assert board(store, later)["projects"][0]["evidence_stale"]


def test_transport_failure_is_a_visible_gap(store, course):
    course.github_enabled = True
    store.save_course(course)
    def offline(request):
        raise httpx.ConnectError("Private provider diagnostics", request=request)
    github = GitHub(transport=httpx.MockTransport(offline))
    try:
        collect_github(store, github)
    finally:
        github.close()
    project = board(store)["projects"][0]
    assert not project["evidence"]["complete"]
    assert "Private provider diagnostics" not in str(project)
