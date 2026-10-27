import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
from test_workspace import HEADERS, PROGRESS, WORKSPACE, combined, sign_in

from ai_mirror.activity import project_activity, timeline
from ai_mirror.app import tick
from ai_mirror.evidence import GitHub, collect_github
from ai_mirror.pinup import PinUpdate, ProjectPin, board, save_pin
from ai_mirror.slack import Slack, SlackError
from ai_mirror.slack_evidence import capture_github, collect_slack, project_event

__all__ = ['combined']


def slack_course(store, course):
    course.activity_source = 'slack'
    course.github_enabled = False
    course.slack_enabled = True
    course.github_slack_app_id = 'AGITHUB'
    course.active = False
    course.meetings = []
    store.save_course(course)
    return course.projects[0]


def test_slack_mode_never_loads_app_credentials_or_reads_github(store, course, settings, slack, monkeypatch):
    slack_course(store, course)
    course.github_enabled = True  # Mode remains authoritative if an old flag is still set.
    course.slack_enabled = False
    store.save_course(course)
    def forbidden(*args, **kwargs):
        raise AssertionError('Direct GitHub access must not run in Slack mode')
    monkeypatch.setattr('ai_mirror.app.credentials', forbidden)
    monkeypatch.setattr('ai_mirror.app.refresh_connections', forbidden)
    monkeypatch.setattr('ai_mirror.evidence.credentials', forbidden)
    configured = GitHub.configured(settings, course)
    configured.close()
    monkeypatch.setattr(GitHub, 'configured', forbidden)
    tick(store, replace(settings, workspace_enabled=True, sends_enabled=False), slack)
    assert collect_github(store, object())['status'] == 'disabled'
    assert not slack.sent and not store.outbox()


def test_timeline_sorts_source_times_paginates_ties_and_excludes_private_learning(store, course):
    project = slack_course(store, course)
    now = datetime.now(timezone.utc)
    source_time = (now - timedelta(hours=1)).isoformat()
    for n in range(45):
        store.add_entry(f'visible-{n:03}', course.students[0].id, course.sprint, 'project_update',
                        f'Update {n}', {'at': source_time, 'url': 'https://example.slack.com/source'})
    store.add_entry('private', course.students[0].id, course.sprint, 'muddiest_point', 'PRIVATE_MUDDY', {}, True)
    store.add_entry('journal', course.students[0].id, course.sprint, 'journal', 'PRIVATE_JOURNAL', {})
    store.add_entry('old', course.students[0].id, 'old-sprint', 'project_update', 'OLD_SPRINT', {})
    store.add_entry('command', course.students[0].id, course.sprint, 'project_update', '/github subscribe list', {})
    store.add_entry('other', course.students[-1].id, course.sprint, 'project_update', 'OTHER_PROJECT', {})
    cursor, events = None, []
    while True:
        page = timeline(store, project, shared=True, cursor=cursor)
        events.extend(page['events'])
        cursor = page['next_cursor']
        if not cursor:
            break
    assert len(events) == 45 and len({e['id'] for e in events}) == 45
    assert all(e['at'] == source_time for e in events)
    assert all('PRIVATE_' not in str(e) and 'OTHER_PROJECT' not in str(e) for e in events)
    assert events[0]['id'] == 'owner/visible-044'
    try:
        timeline(store, project, cursor=base64.urlsafe_b64encode(b'[null,1]').decode())
        assert False, 'Malformed cursor must be rejected'
    except ValueError:
        pass


def test_pin_history_respects_sharing_and_retention(store, course):
    project = slack_course(store, course)
    private = save_pin(store, project.id, PinUpdate(pin=ProjectPin(
        goal='PRIVATE_COACHING', source_url='https://example.org/private')))
    shared = save_pin(store, project.id, PinUpdate(expected_revision=private['revision'], pin=ProjectPin(
        shared=True, goal='Public goal', source_url='https://example.org/shared')))
    events = project_activity(store, project, shared=True)
    assert len(events) == 1 and events[0]['pin']['goal'] == 'Public goal'
    assert 'PRIVATE_COACHING' not in str(events)
    assert len(project_activity(store, project)) == 2
    save_pin(store, project.id, PinUpdate(expected_revision=shared['revision'], pin=ProjectPin(
        shared=False, goal='Withdrawn goal', source_url='https://example.org/shared')))
    assert not project_activity(store, project, shared=True)
    store.purge((datetime.now(timezone.utc) + timedelta(days=91)).isoformat())
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM pin_history').fetchone()[0] == 0


def test_slack_mode_status_has_no_install_requirement_and_remains_course_scoped(combined, store, course, monkeypatch):
    client, app, config, *_ = combined
    slack_course(store, course)
    monkeypatch.setattr('ai_mirror.github_app.AppProvider.info', lambda *_: (_ for _ in ()).throw(AssertionError()))
    sign_in(client, store, course.students[0].slack_id)
    data = client.get(WORKSPACE + '/api/github').json()
    assert data['source'] == 'slack' and data['app']['retired'] and not data['can_register']
    assert len(data['projects']) == 1 and 'github_login' not in data
    assert 'install_url' not in str(data)
    endpoint = '/entr/5000/2026/fall/api/projects/' + course.projects[0].id + '/timeline'
    assert client.get(endpoint).status_code == 200
    assert client.get(endpoint + '?cursor=invalid!').status_code == 400
    assert client.post('/entr/5000/2026/fall/api/collect-slack', headers=HEADERS).status_code == 403
    sign_in(client, store, 'U5500ALEX')
    assert client.get(WORKSPACE + '/api/github').status_code == 403
    assert client.get(endpoint).status_code == 403
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 200
    sign_in(client, store, course.instructor_slack_ids[0])
    assert client.post(WORKSPACE + '/api/github/registration', headers=HEADERS).status_code == 410
    assert client.post(WORKSPACE + '/hooks/github', json={}).json()['status'] == 'ignored'
    assert not store.outbox()


def test_thread_recovery_uses_existing_scope_caches_quiet_threads_and_preserves_sources(store, course):
    project = slack_course(store, course)
    now = datetime.now(timezone.utc)
    parent = str((now - timedelta(days=2)).timestamp())
    reply = str((now - timedelta(days=1)).timestamp())
    class Reader:
        def __init__(self):
            self.calls = []
        def call(self, method, payload):
            self.calls.append(method)
            if method == 'auth.test':
                return {'team_id': course.workspace_id, 'url': 'https://example.slack.com/'}
            if method == 'conversations.history':
                return {'messages': [{'ts': parent, 'user': course.students[0].slack_id,
                                      'text': 'Initial test', 'reply_count': 2, 'latest_reply': reply}]}
            assert method == 'conversations.replies'
            return {'messages': [{'ts': reply, 'thread_ts': parent, 'user': course.students[0].slack_id,
                                  'text': 'The follow-up result'},
                                 {'ts': reply + '1', 'thread_ts': parent, 'user': 'USTRANGER', 'text': 'Unscoped'},
                                 {'ts': reply + '2', 'user': course.students[0].slack_id,
                                  'text': '/github subscribe list'}]}
    reader = Reader()
    collect_slack(store, reader, now, project_ids={project.id})
    assert reader.calls.count('conversations.replies') == 1
    events = project_activity(store, project, shared=True)
    assert [e['text'] for e in events] == ['The follow-up result', 'Initial test']
    assert events[0]['at'] == datetime.fromtimestamp(float(reply), timezone.utc).isoformat()
    collect_slack(store, reader, now, project_ids={project.id})
    assert reader.calls.count('conversations.replies') == 1
    assert store.get(f'slack_collection/{project.id}')['complete']
    assert not store.get('last_slack_collection')  # A scoped sync cannot claim all projects were read.


def test_thread_read_failure_is_visible_and_never_marks_full_coverage(store, course):
    project = slack_course(store, course)
    ts = str(datetime.now(timezone.utc).timestamp())
    class Reader:
        def call(self, method, payload):
            if method == 'auth.test':
                return {'team_id': course.workspace_id}
            if method == 'conversations.history':
                return {'messages': [{'ts': ts, 'reply_count': 1, 'latest_reply': ts}]}
            raise SlackError('missing_scope')
    result = collect_slack(store, Reader(), project_ids={project.id})
    state = store.get(f'slack_collection/{project.id}')
    assert state['history_complete'] and not state['complete']
    assert 'missing_scope' in state['warning'] and result['warnings']


def test_github_feed_keeps_only_titles_and_withdraws_edited_notifications(store, course):
    project = slack_course(store, course)
    ts = str(datetime.now(timezone.utc).timestamp())
    message = {'ts': ts, 'app_id': 'AGITHUB', 'bot_id': 'BBOT', 'attachments': [{
        'title': f'<https://github.com/{project.repository}/pull/7|#7 Test result>',
        'fallback': f'[{project.repository}] Pull request merged by alex', 'text': 'PRIVATE_NOTIFICATION_BODY'}]}
    assert capture_github(store, course, message, project.channel_id)
    events = project_activity(store, project, shared=True)
    assert len(events) == 1 and events[0]['event'] == 'Pull request merged'
    assert events[0]['github_url'].endswith('/pull/7')
    assert 'PRIVATE_NOTIFICATION_BODY' not in str(events)
    project_event(store, {'team_id': course.workspace_id, 'event': {
        'type': 'message', 'channel': project.channel_id, 'subtype': 'message_changed',
        'message': {**message, 'attachments': []}}})
    assert not project_activity(store, project, shared=True)


def test_slack_mode_hides_old_direct_reads_but_keeps_archived_records(store, course):
    project = slack_course(store, course)
    key = f'project_evidence/{course.sprint}/{project.id}'
    store.set(key, {'complete': True, 'items': [{'text': 'OLD_DIRECT_ITEM'}]})
    projection = board(store)
    assert 'OLD_DIRECT_ITEM' not in json.dumps(projection)
    assert store.get(key)['items'][0]['text'] == 'OLD_DIRECT_ITEM'


def test_thread_transport_uses_get_query_parameters(monkeypatch):
    seen = []
    def request(url, **kwargs):
        seen.append((url, kwargs))
        return httpx.Response(200, json={'ok': True, 'messages': []})
    monkeypatch.setattr(httpx, 'get', request)
    Slack('test-token').call('conversations.replies', {'channel': 'CTEST', 'ts': '123.456', 'limit': 100})
    assert seen[0][1]['params']['ts'] == '123.456'
    assert 'json' not in seen[0][1]


def test_history_reconciliation_preserves_events_arriving_during_a_sync(store, course):
    project = slack_course(store, course)
    started = datetime.now(timezone.utc)
    fresh = str((started + timedelta(seconds=1)).timestamp())
    class Reader:
        def call(self, method, payload):
            if method == 'auth.test':
                return {'team_id': course.workspace_id}
            from ai_mirror.slack_evidence import capture
            capture(store, course, {'ts': fresh, 'user': course.students[0].slack_id,
                                   'text': 'Arrived while history was loading'}, project.channel_id)
            return {'messages': []}
    collect_slack(store, Reader(), started, project_ids={project.id})
    assert project_activity(store, project)[0]['text'] == 'Arrived while history was loading'


def test_github_subscription_receipts_are_not_project_activity(store, course):
    project = slack_course(store, course)
    assert not capture_github(store, course, {'ts': str(datetime.now(timezone.utc).timestamp()),
        'app_id': 'AGITHUB', 'bot_id': 'BBOT', 'attachments': [{
            'title': f'Subscribed to <https://github.com/{project.repository}|repository>',
            'fallback': 'Subscribed to the following'}]}, project.channel_id)
