from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from ai_mirror.app import tick
from ai_mirror.evidence import GitHub


@pytest.mark.parametrize('recent_scan', [False, True])
def test_webhook_refresh_reuses_a_due_full_scan_and_preserves_live_updates(store, course, settings, slack, monkeypatch, recent_scan):
    course = course.model_copy(update={'active': False, 'github_enabled': True, 'slack_enabled': False, 'meetings': []})
    store.save_course(course)
    checked = datetime.now(timezone.utc).isoformat()
    if recent_scan:
        store.set('last_github_collection', {'at': checked})
    calls = []
    def provider(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=[])
    github = GitHub(transport=httpx.MockTransport(provider))
    monkeypatch.setattr('ai_mirror.app.refresh_connections', lambda *_: [course.projects[0].id])
    monkeypatch.setattr(GitHub, 'configured', lambda *_: github)
    tick(store, replace(settings, workspace_enabled=True, sends_enabled=False), slack)
    projects = course.projects[:1] if recent_scan else course.projects
    expected = {f'/repos/{p.repository}/{kind}' for p in projects for kind in ('commits', 'issues')}
    assert set(calls) == expected and len(calls) == len(expected)
    assert not slack.sent
    if recent_scan:
        assert store.get('last_github_collection')['at'] == checked
