import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from ai_mirror.app import create_app
from ai_mirror.store import content_hash


@pytest.fixture
def client(settings, store, slack):
    with TestClient(create_app(settings, store, slack)) as client:
        yield client


@pytest.fixture
def auth(settings):
    return {'Authorization': f'Bearer {settings.admin_token}'}


def signed(secret, body, timestamp=None):
    timestamp = str(timestamp or int(time.time()))
    sig = hmac.new(secret.encode(), b'v0:' + timestamp.encode() + b':' + body, hashlib.sha256).hexdigest()
    return {'X-Slack-Request-Timestamp': timestamp, 'X-Slack-Signature': 'v0=' + sig}


def test_public_downloads_and_private_api(client):
    assert client.get('/healthz').json()['status'] == 'ok'
    assert client.get('/').status_code == 200
    assert client.get('/skill.md').status_code == 200
    assert client.get('/api/status').status_code == 401
    assert client.get('/api/entries').status_code == 401
    assert client.get('/api/digests/missing').status_code == 401


def test_signature_replay_and_tamper_rejected(client, settings):
    body = b'{"type":"url_verification","challenge":"hello"}'
    assert client.post('/slack/events', content=body).status_code == 401
    assert client.post('/slack/events', content=body, headers=signed(settings.slack_signing_secret, body, 1)).status_code == 401
    assert client.post('/slack/events', content=body + b' ', headers=signed(settings.slack_signing_secret, body)).status_code == 401
    assert client.post('/slack/events', content=body, headers=signed(settings.slack_signing_secret, body)).json() == {'challenge': 'hello'}


def test_course_activation_rejects_wrong_workspace(client, auth, course, slack):
    slack.team_id = 'TOTHER'
    response = client.put('/api/course', headers=auth, json=course.model_dump(mode='json'))
    assert response.status_code == 400 and 'another workspace' in response.text


def test_signed_private_command_visible_only_to_instructor(client, settings, auth):
    raw = urlencode({'team_id': 'TDEMO', 'user_id': 'UALEX', 'channel_id': 'CGARDEN',
                     'trigger_id': 'test-command', 'text': 'muddy Something I want private.'}).encode()
    result = client.post('/slack/commands', content=raw, headers=signed(settings.slack_signing_secret, raw))
    assert result.status_code == 200 and 'Something I want private' not in result.text
    entries = client.get('/api/entries', headers=auth).json()['entries']
    assert entries[0]['private'] == 1
    assert client.get('/api/entries').status_code == 401


def test_digest_does_not_queue_feedback_and_approval_is_exact(client, auth, store):
    store.add_entry('note', 'alex', 'sprint-3', 'exit_ticket', 'I tried a smaller experiment.', {'url': 'https://example.com'})
    digest = client.post('/api/digests', headers=auth).json()
    assert len(digest['students']) == 4
    assert store.outbox() == []
    row = digest['students'][0]
    approval = {'digest_id': digest['id'], 'student_id': row['student_id'], 'draft_hash': content_hash(row),
                'text': 'What surprised you?', 'reviewed': False}
    assert client.post('/api/feedback', headers=auth, json=approval).status_code == 400
    approval['reviewed'] = True
    approval['draft_hash'] = 'wrong'
    assert client.post('/api/feedback', headers=auth, json=approval).status_code == 400
    approval['draft_hash'] = content_hash(row)
    response = client.post('/api/feedback', headers=auth, json=approval)
    assert response.status_code == 200
    assert len(store.outbox()) == 1
    assert client.post('/api/feedback', headers=auth, json=approval).status_code == 200
    assert len(store.outbox()) == 1
    approval['text'] = 'Changed after queueing'
    assert client.post('/api/feedback', headers=auth, json=approval).status_code == 400


def test_private_note_not_reproduced_in_default_feedback(client, auth, store):
    store.add_entry('private', 'alex', 'sprint-3', 'muddiest_point', 'Sensitive personal fact', {}, True)
    digest = client.post('/api/digests', headers=auth).json()
    row = next(r for r in digest['students'] if r['student_id'] == 'alex')
    assert 'Sensitive personal fact' not in row['feedback']
    assert 'private reflection' in row['summary']


def test_hold_and_recovery_requires_resolution(client, auth, store):
    store.enqueue('message', 'feedback', {'channel': 'CGARDEN'}, '2026-01-01T00:00:00+00:00')
    store.finish('message', 'uncertain')
    assert client.post('/api/hold', headers=auth).json()['held']
    release = {'action': 'release_hold', 'reason': 'Checked Slack history and receipts'}
    assert client.post('/api/release-hold', headers=auth, json=release).status_code == 400
    assert client.post('/api/outbox/message/reconcile', headers=auth,
                       json={'action': 'cancel', 'reason': 'Confirmed this message is no longer needed'}).status_code == 200
    assert client.post('/api/release-hold', headers=auth, json=release).status_code == 200


def test_feedback_and_json_are_not_public_html(client, auth, store):
    store.add_entry('x', 'alex', 'sprint-3', 'exit_ticket', '<script>steal()</script>', {})
    page = client.get('/instructor')
    assert '<script>steal()</script>' not in page.text
    assert "frame-ancestors 'none'" in page.headers['content-security-policy']
    response = client.get('/api/entries', headers=auth)
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['entries'][0]['text'] == '<script>steal()</script>'
