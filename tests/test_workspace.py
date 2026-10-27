import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_dashboard import oidc_provider

from ai_mirror.app import create_app
from ai_mirror.course_context import CourseContext
from ai_mirror.dashboard import COOKIE, digest
from ai_mirror.progress import Progress

ORIGIN = 'https://jweath.com'
MIRROR = '/entr/5000/2026/fall'
WORKSPACE = '/entr/workspace'
PROGRESS = '/entr/5500/2026/fall'
HEADERS = {'Origin': ORIGIN, 'X-CSRF-Token': 'csrf-value'}


@pytest.fixture
def combined(tmp_path, settings, store, course):
    roster = {'workspace_id': course.workspace_id, 'instructor_slack_ids': course.instructor_slack_ids,
              'groups': [
                  {'id': '1135-a', 'section': '1135', 'name': 'Morning A', 'channel_id': 'CGROUPA',
                   'members': [{'name': 'Alex', 'slack_id': 'U5500ALEX'}]},
                  {'id': '1135-b', 'section': '1135', 'name': 'Morning B', 'channel_id': 'CGROUPB',
                   'members': [{'name': 'Blair', 'slack_id': 'UBLAIR'}]},
                  {'id': '255-a', 'section': '255', 'name': 'Afternoon A', 'channel_id': 'CGROUPC',
                   'members': [{'name': 'Casey', 'slack_id': 'UCASEY'}]},
              ]}
    path = tmp_path / 'groups.json'
    path.write_text(json.dumps(roster))
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps({'enrollment_snapshot': {
        'checked_at': datetime.now(timezone.utc).isoformat(), 'source': 'Participation enrollment snapshot',
        'students': [{'name': name, 'slack_id': sid, 'source_id': 'source-' + sid, 'section': section}
                     for sid, name, section in [('U5500ALEX', 'Alex', '1135'), ('UBLAIR', 'Blair', '1135'),
                                                ('UCASEY', 'Casey', '255'), ('UUNGROUPED', 'Unassigned student', '1135')]]}}))
    config = replace(settings, workspace_enabled=True, progress_roster_path=str(path),
                     progress_db_path=str(tmp_path / 'progress.db'), directory_sources_path=str(sources),
                     session_secret='s' * 48, slack_client_id='client-id', slack_client_secret='client-secret')
    app = create_app(config, store)
    app.state.workspace.state.context.transport = httpx.MockTransport(lambda request: httpx.Response(503))
    # Model the public reverse-proxy mounts without weakening the app's auth.
    outer = FastAPI()
    mounts = {r.path: r.app for r in app.routes if hasattr(r, 'app')}
    outer.mount(MIRROR, mounts['/course'])
    outer.mount(WORKSPACE, mounts['/workspace'])
    outer.mount(PROGRESS, mounts['/progress'])
    with TestClient(outer, base_url=ORIGIN, follow_redirects=False) as client:
        yield client, app, config, path, sources, mounts['/course']


def sign_in(client, store, user):
    with store.connect() as db:
        db.execute('INSERT OR REPLACE INTO browser_sessions VALUES (?,?,?,?)',
                   (digest('shared-session'), user, 'csrf-value', time.time() + 3600))
    client.cookies.set(COOKIE, 'shared-session', domain='jweath.com', path='/entr/')


def test_anonymous_and_students_cannot_read_private_workspace(combined, store):
    client, _, _, _, _, _ = combined
    assert client.get(WORKSPACE + '/api/overview').status_code == 401
    assert client.get(WORKSPACE + '/api/directory').status_code == 401
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 401
    assert 'Alex' not in client.get(WORKSPACE + '/').text
    sign_in(client, store, 'U5500ALEX')
    for path in ('/api/overview', '/api/directory', '/instructor/'):
        assert client.get(WORKSPACE + path).status_code == 403
    home = client.get(WORKSPACE + '/api/home').json()
    assert len(home['courses']) == 1 and home['courses'][0]['section'] == '1135'
    assert home['courses'][0]['my_work']['name'] == 'Morning A'
    assert 'Casey' not in json.dumps(home)
    assert client.get(MIRROR + '/api/board').status_code == 403
    assert client.get(MIRROR + '/instructor/api/status').status_code == 403
    assert client.get(PROGRESS + '/api/sections/255').status_code == 403


def test_same_cookie_serves_both_courses_only_with_explicit_grants(combined, store, course):
    client, _, _, path, _, _ = combined
    roster = json.loads(path.read_text())
    roster['instructor_slack_ids'] = ['UOTHERTEACHER']
    path.write_text(json.dumps(roster))
    sign_in(client, store, course.instructor_slack_ids[0])
    directory = client.get(WORKSPACE + '/api/directory').json()
    assert all(s['course'] == '5000' for s in directory['sections'])
    assert client.get(MIRROR + '/instructor/api/status').status_code == 200
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 403
    sign_in(client, store, 'UOTHERTEACHER')
    assert client.get(PROGRESS + '/api/sections/255').status_code == 200
    assert client.get(MIRROR + '/instructor/api/status').status_code == 403
    assert all(s['course'] == '5500' for s in client.get(WORKSPACE + '/api/directory').json()['sections'])


def test_enrollment_survives_missing_group_but_cannot_edit_other_groups(combined, store):
    client, _, _, _, _, _ = combined
    sign_in(client, store, 'UUNGROUPED')
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 200
    home = client.get(WORKSPACE + '/api/home').json()
    assert 'my_work' not in home['courses'][0]
    assert client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS,
                      json={'revision': 0, 'progress': {'next_step': 'Change another group'}}).status_code == 403


def test_student_in_both_classes_gets_both_explicit_enrollments(combined, store, course):
    client, _, _, path, sources, _ = combined
    sid = course.students[0].slack_id
    for file in (path, sources):
        file.write_text(file.read_text().replace('U5500ALEX', sid))
    sign_in(client, store, sid)
    home = client.get(WORKSPACE + '/api/home').json()
    assert {c['course'] for c in home['courses']} == {'5000', '5500'}
    assert client.get(MIRROR + '/api/board').status_code == 200
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 200
    assert client.get(PROGRESS + '/api/sections/255').status_code == 403
    assert client.get(WORKSPACE + '/api/overview').status_code == 403


def test_revocation_reads_source_again_and_never_infers_membership_from_name(combined, store):
    client, _, _, _, sources, _ = combined
    sign_in(client, store, 'U5500ALEX')
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 200
    data = json.loads(sources.read_text())
    data['enrollment_snapshot']['students'][0]['slack_id'] = 'UNEWALEX'
    sources.write_text(json.dumps(data))
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 401
    assert client.get(WORKSPACE + '/api/home').status_code == 401
    sign_in(client, store, 'UNEWALEX')
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 200
    assert 'my_work' not in client.get(WORKSPACE + '/api/home').json()['courses'][0]


def test_group_edits_have_csrf_ownership_revision_history_and_no_grading(combined, store):
    client, _, _, _, _, _ = combined
    sign_in(client, store, 'U5500ALEX')
    payload = {'revision': 0, 'progress': {'interview': 'completed', 'next_step': 'Draft together'}}
    assert client.put(PROGRESS + '/api/groups/1135-a', json=payload).status_code == 403
    assert client.put(PROGRESS + '/api/groups/1135-a', headers={**HEADERS, 'Origin': 'https://evil.test'},
                      json=payload).status_code == 403
    assert client.put(PROGRESS + '/api/groups/1135-b', headers=HEADERS, json=payload).status_code == 403
    assert client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS,
                      json={**payload, 'progress': {'verified': True}}).status_code == 403
    assert client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS,
                      json={**payload, 'progress': {'presentation_date': '2026-11-12'}}).status_code == 403
    saved = client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS, json=payload)
    assert saved.status_code == 200 and saved.json()['revision'] == 1
    assert client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS, json=payload).status_code == 409
    assert len(client.get(PROGRESS + '/api/groups/1135-a/history').json()['updates']) == 1
    assert client.post(WORKSPACE + '/api/logout', headers=HEADERS).status_code == 200
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 401
    assert client.get(WORKSPACE + '/api/home').status_code == 401


def test_project_timeline_is_section_scoped_and_includes_current_changes(combined, store, course):
    client, _, _, _, _, _ = combined
    endpoint = PROGRESS + '/api/groups/1135-a/timeline'
    assert client.get(endpoint).status_code == 401
    sign_in(client, store, 'U5500ALEX')
    initial = client.get(endpoint).json()
    assert [u['revision'] for u in initial['updates']] == [0]
    assert initial['updates'][0]['changes'] == []
    assert initial['next_before'] is None
    for revision, progress in enumerate([
        {'entrepreneur': 'Morgan', 'interview': 'scheduled', 'scheduled_date': '2026-10-20'},
        {'entrepreneur': 'Morgan', 'interview': 'completed', 'completed_date': '2026-10-20',
         'source_url': 'https://example.org/interview', 'verified': True},
    ]):
        if progress.get('verified'):
            sign_in(client, store, course.instructor_slack_ids[0])
        assert client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS,
                          json={'revision': revision, 'progress': progress}).status_code == 200
    sign_in(client, store, 'UBLAIR')  # Same-section peers may view, but cannot edit this group.
    updates = client.get(endpoint).json()['updates']
    assert [u['revision'] for u in updates] == [2, 1, 0]
    assert updates[0]['progress']['verified'] is True
    changes = {c['field']: c for c in updates[0]['changes']}
    assert changes['interview'] == {'field': 'interview', 'before': 'scheduled', 'after': 'completed'}
    assert changes['scheduled_date']['after'] is None  # Removed values remain visible in the timeline.
    assert 'entrepreneur' not in changes  # An unchanged field is not presented as a new update.
    assert client.get(PROGRESS + '/api/groups/255-a/timeline').status_code == 404
    assert client.get(PROGRESS + '/api/groups/not-a-group/timeline').status_code == 404
    assert client.get(endpoint + '?before=0').status_code == 422
    sign_in(client, store, 'UCASEY')
    assert client.get(endpoint + '?before=2').status_code == 404
    assert not store.outbox()


def test_project_timeline_paginates_without_gaps_or_losing_boundary_changes(combined, store):
    client, app, _, _, _, _ = combined
    progress_app = next(r.app for r in app.routes if getattr(r, 'path', None) == '/progress')
    progress_store = progress_app.state.store
    sign_in(client, store, 'U5500ALEX')
    for revision in range(43):
        response = client.put(PROGRESS + '/api/groups/1135-a', headers=HEADERS,
                              json={'revision': revision, 'progress': {'next_step': f'Step {revision + 1}'}})
        assert response.status_code == 200
    # Equal save times must not cause missing or duplicate events.
    with progress_store.connect() as db:
        db.execute("UPDATE groups SET updated='2026-10-27T14:00:00+00:00'")
        db.execute("UPDATE history SET updated='2026-10-27T14:00:00+00:00'")
    before, seen, pages = None, [], []
    while True:
        page = client.get(PROGRESS + '/api/groups/1135-a/timeline' +
                          (f'?before={before}' if before is not None else '')).json()
        pages.append(page)
        seen.extend(u['revision'] for u in page['updates'])
        before = page['next_before']
        if before is None:
            break
    assert [len(p['updates']) for p in pages] == [20, 20, 4]
    assert seen == list(range(43, -1, -1))
    assert pages[0]['updates'][-1]['changes'] == [
        {'field': 'next_step', 'before': 'Step 23', 'after': 'Step 24'}]
    assert pages[1]['updates'][0]['changes'] == [
        {'field': 'next_step', 'before': 'Step 22', 'after': 'Step 23'}]
    assert pages[-1]['updates'][-1]['revision'] == 0
    assert not store.outbox()


def test_instructor_projection_separates_missing_evidence_and_group_reports(combined, store, course):
    client, _, _, _, _, _ = combined
    store.add_entry('private-muddy', course.students[0].id, course.sprint, 'muddiest_point', 'PRIVATE_MUDDY', {}, True)
    sign_in(client, store, course.instructor_slack_ids[0])
    response = client.get(WORKSPACE + '/api/overview')
    assert response.status_code == 200
    data = response.json()
    assert len(data['courses']) == 3
    assert next(c for c in data['courses'] if c['section'] == '1135')['students'] == 3
    assert any(a['id'] == 'ungrouped-UUNGROUPED' for a in data['alerts'])
    assert not any(c['course'] == '5500' for c in data['changes'])  # imports aren't new group reports
    groups = [p for p in data['projects'] if p['course'] == '5500']
    assert len(groups) == 3
    morning = next(p for p in groups if p['section'] == '1135' and p['name'] == 'Morning A')
    assert morning['overview_url'] == PROGRESS + '/1135/#group=1135-a'
    assert morning['progress']['interview'] == 'unknown'
    assert 'PRIVATE_MUDDY' not in response.text
    assert data['participation']['connected'] is False
    assert not store.outbox()


def test_malformed_or_wrong_workspace_roster_fails_closed_without_breaking_5000(combined, store, course):
    client, _, _, path, _, _ = combined
    data = json.loads(path.read_text())
    data['workspace_id'] = 'TOTHER'
    path.write_text(json.dumps(data))
    sign_in(client, store, 'U5500ALEX')
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 401
    sign_in(client, store, course.students[0].slack_id)
    assert client.get(MIRROR + '/api/board').status_code == 200


def test_oidc_reuses_registered_callback_with_scoped_5500_grant(combined, store, course):
    client, _, _, _, _, dashboard = combined
    nonce = oidc_provider(dashboard, course, {'https://slack.com/user_id': 'U5500ALEX'})
    start = client.get(MIRROR + '/auth/slack?next=5500-1135')
    params = parse_qs(urlsplit(start.headers['location']).query)
    nonce['nonce'] = params['nonce'][0]
    assert params['redirect_uri'] == [ORIGIN + MIRROR + '/auth/callback']
    result = client.post(MIRROR + '/auth/callback', data={'code': 'valid', 'state': params['state'][0]})
    assert result.status_code == 303 and result.headers['location'] == ORIGIN + PROGRESS + '/1135/'
    assert 'Path=/entr/' in result.headers['set-cookie'] and 'HttpOnly' in result.headers['set-cookie']
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 200
    assert client.get(MIRROR + '/api/board').status_code == 403
    assert 'provider-token-never-stored' not in str(client.cookies)


def test_dates_and_urls_cannot_claim_completion_or_execute_content():
    assert Progress(interview='scheduled', scheduled_date='2026-09-01').interview == 'scheduled'
    for fields in ({'completed_date': '2026-09-01'}, {'interview': 'completed', 'completed_date': '2999-01-01'},
                   {'source_url': 'javascript:alert(1)'}, {'document_url': 'https://secret@example.com'}):
        with pytest.raises(ValueError):
            Progress(**fields)


def test_published_context_has_expiry_and_never_uses_unverified_fallback():
    publication = {'version': 1, 'courses': [{'course': '5500', 'section': '1135', 'title': 'ENTR 5500',
        'updated_at': '2026-10-22T12:00:00-04:00', 'through': '2026-10-27T23:59:59-04:00',
        'home_url': '/entr/5500/', 'actions': [{'id': 'prep', 'title': '<script>not instructions</script>',
        'detail': 'Read the source', 'due': '2026-10-27T11:35:00-04:00', 'until': None,
        'source_url': '/entr/5500/notes/2026-10-22/', 'href': '/entr/5500/assignments/'}]}]}
    context = CourseContext(httpx.MockTransport(lambda request: httpx.Response(200, json=publication)))
    active = context.for_section('5500', '1135', datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert active['connected'] and len(active['actions']) == 1
    assert context.for_section('5500', '1135', datetime(2026, 10, 29, tzinfo=timezone.utc))['actions'] == []
    unavailable = CourseContext(httpx.MockTransport(lambda request: httpx.Response(503)))
    assert unavailable.for_section('5500', '1135')['connected'] is False
    publication['courses'][0]['actions'][0]['href'] = 'javascript:alert(1)'
    unsafe = CourseContext(httpx.MockTransport(lambda request: httpx.Response(200, json=publication)))
    assert unsafe.for_section('5500', '1135')['connected'] is False
