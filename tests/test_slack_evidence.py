from ai_mirror.slack_evidence import collect_slack, project_event


def test_collection_reads_only_registered_project_owner_updates(store, course):
    course.slack_enabled = True
    store.save_course(course)
    student = course.students[0]
    class Reader:
        def call(self, method, params):
            if method == "auth.test":
                return {"team_id": course.workspace_id, "url": "https://example.slack.com/"}
            assert method == "conversations.history"
            return {"messages": [
                {"ts": "1792600000.000001", "user": student.slack_id, "text": "Owner update"},
                {"ts": "1792600000.000002", "user": "USTRANGER", "text": "Peer comment"},
                {"ts": "1792600000.000003", "user": student.slack_id, "bot_id": "BTEST", "text": "Bot"},
            ]}
    collect_slack(store, Reader())
    entries = [e for e in store.entries(course.sprint) if e["kind"] == "project_update"]
    assert len(entries) == 1 and entries[0]["text"] == "Owner update"
    assert entries[0]["source"]["url"].startswith("https://example.slack.com/archives/")
    channel = course.project(student).channel_id
    project_event(store, {"team_id": course.workspace_id, "event": {
        "type": "message", "subtype": "message_deleted", "channel": channel, "deleted_ts": "1792600000.000001"}})
    assert not store.entries(course.sprint)
