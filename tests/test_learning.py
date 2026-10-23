# ruff: noqa: F811
import json
from dataclasses import replace

import httpx
from test_workspace import WORKSPACE, combined, sign_in  # noqa: F401

from ai_mirror.learning import photo_url


def snapshot():
    students = [
        {
            "slack_id": sid,
            "group": "Morning A",
            "case": "Dropbox",
            "response": {
                "text": "Customer pricing question",
                "question": "How to price?",
                "recommendation": "Keep it simple",
                "detail": "Case quote",
                "complete": True,
                "url": "https://ugaentr.slack.com/archives/CA/p123",
            },
            "at_cutoff": None,
        }
        for sid in ["U5500ALEX", "UBLAIR", "UUNKNOWN"]
    ]
    return {
        "checked_at": "2026-10-23T12:00:00Z",
        "assignments": [
            {
                "id": "case",
                "title": "Case prep",
                "source_url": "https://example.test",
                "sections": [
                    {
                        "id": "26f-5500-jw-1135",
                        "starts_at": "2026-10-27T11:35:00-04:00",
                        "prep_cutoff": "2026-10-27T09:35:00-04:00",
                        "students": students,
                        "channels": [],
                    },
                    {
                        "id": "26f-5500-jw-255",
                        "starts_at": "2026-10-27T14:55:00-04:00",
                        "prep_cutoff": "2026-10-27T12:55:00-04:00",
                        "students": [
                            {
                                "slack_id": "UCASEY",
                                "name": "Casey",
                                "group": "Afternoon A",
                                "case": "Cork’d",
                                "response": None,
                                "at_cutoff": None,
                            }
                        ],
                        "channels": [],
                    },
                ],
            }
        ],
        "reflections": [
            {
                "slack_id": sid,
                "section": "26f-5500-jw-" + section,
                "date": "2026-10-22",
                "takeaway": "private-" + sid,
                "muddy": "Private uncertainty",
                "next_question": "Next",
            }
            for sid, section in [("U5500ALEX", "1135"), ("UBLAIR", "1135"), ("UCASEY", "255")]
        ],
        "profiles": {
            "U5500ALEX": {"url": "https://avatars.slack-edge.com/alex.jpg"},
            "UBLAIR": {"url": "https://evil.test/pixel"},
        },
    }


def connect(app, config, store):
    app.state.learning.settings = replace(config, learning_token="b" * 40)
    app.state.learning.transport = httpx.MockTransport(lambda req: httpx.Response(200, json=snapshot()))
    return app.state.learning.snapshot()


def test_private_prep_and_reflections_only_release_own_record(combined, store):
    client, app, config, *_ = combined
    connect(app, config, store)
    assert client.get(WORKSPACE + "/api/my-learning").status_code == 401
    sign_in(client, store, "U5500ALEX")
    data = client.get(WORKSPACE + "/api/my-learning").json()
    assert len(data["assignments"][0]["sections"]) == 1
    section = data["assignments"][0]["sections"][0]
    assert [s["slack_id"] for s in section["students"]] == ["U5500ALEX"]
    assert "channels" not in section
    assert [r["slack_id"] for r in data["reflections"]] == ["U5500ALEX"]
    assert "UBLAIR" not in json.dumps(data) and "UCASEY" not in json.dumps(data)
    assert client.get(WORKSPACE + "/api/learning").status_code == 403


def test_instructor_prep_joins_exact_ids_and_filters_unknown_students(combined, store, course):
    client, app, config, *_ = combined
    connect(app, config, store)
    sign_in(client, store, course.instructor_slack_ids[0])
    data = client.get(WORKSPACE + "/api/learning").json()
    assert len(data["assignments"][0]["sections"]) == 2
    assert "UUNKNOWN" not in json.dumps(data)
    assert data["assignments"][0]["sections"][0]["students"][0]["name"] == "Alex"
    assert data["assignments"][0]["sections"][0]["topics"]
    assert "profiles" not in data


def test_instructor_without_5500_grant_cannot_read_its_prep(combined, store, course):
    client, app, config, path, *_ = combined
    connect(app, config, store)
    roster = json.loads(path.read_text())
    roster["instructor_slack_ids"] = ["UOTHER"]
    path.write_text(json.dumps(roster))
    sign_in(client, store, course.instructor_slack_ids[0])
    data = client.get(WORKSPACE + "/api/learning").json()
    assert data["assignments"] == [] and data["reflections"] == []


def test_failed_source_keeps_last_read_and_marks_stale(combined, store):
    _, app, config, *_ = combined
    connect(app, config, store)
    app.state.learning.transport = httpx.MockTransport(lambda req: httpx.Response(503))
    data = app.state.learning.snapshot(force=True)
    assert data["assignments"] and not data["connected"] and data["error"]


def test_photos_map_to_project_members_without_profile_email(combined, store, course):
    client, app, config, *_ = combined
    connect(app, config, store)
    store.set(
        "learning_profiles",
        {
            **store.get("learning_profiles"),
            course.students[0].slack_id: "https://avatars.slack-edge.com/owner.jpg",
        },
    )
    sign_in(client, store, course.instructor_slack_ids[0])
    morning = client.get("/entr/5500/2026/fall/api/sections/1135").json()
    assert morning["groups"][0]["member_profiles"][0]["photo"] == "https://avatars.slack-edge.com/alex.jpg"
    assert morning["groups"][1]["member_profiles"][0]["photo"] == ""
    board = client.get("/entr/5000/2026/fall/api/board").json()
    assert any(
        o.get("photo") == "https://avatars.slack-edge.com/owner.jpg"
        for p in board["projects"]
        for o in p["owners"]
    )
    assert all(
        not photo_url(url)
        for url in [
            "https://evil.test/a",
            "http://avatars.slack-edge.com/a",
            "https://user@avatars.slack-edge.com/a",
        ]
    )
