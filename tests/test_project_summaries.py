from datetime import datetime, timedelta, timezone

import pytest
from test_dashboard import PREFIX, dashboard, seed_session

from ai_mirror.pinup import PinConflict, PinUpdate, ProjectPin, board, save_pin
from ai_mirror.project_summaries import SummaryUpdate, review_packet, save_summaries, summary_events

__all__ = ['dashboard']


def packet(store, course):
    student = course.students[0]
    store.add_entry('source', student.id, course.sprint, 'project_update',
                    'Tested the prototype; launch is still planned.',
                    {'url': 'https://example.slack.com/source', 'at': datetime.now(timezone.utc).isoformat()})
    return review_packet(store, student.project_id)


def draft(p):
    source = p['evidence'][0]
    return {'id': 'prototype-test', 'title': 'Prototype tested; launch still planned',
            'text': 'The team tested its prototype. Launch remains a future step.',
            'sources': {source['id']: source['fingerprint']}}


def test_summary_projection_revisions_and_edited_or_deleted_evidence(store, course):
    p = packet(store, course)
    project = course.projects[0]
    saved = save_summaries(store, project.id, SummaryUpdate(summaries=[draft(p)]))
    assert summary_events(store, project)[0]['title'].startswith('Prototype tested')
    assert board(store, shared=True)['projects'][0]['recent_activity'][0]['kind'] == 'summary'
    with pytest.raises(PinConflict):
        save_summaries(store, project.id, SummaryUpdate(summaries=[]))
    store.add_entry('source', course.students[0].id, course.sprint, 'project_update', 'CORRECTED RESULT', {})
    assert not summary_events(store, project)
    with pytest.raises(PinConflict):
        save_summaries(store, project.id, SummaryUpdate(summaries=[draft(p)], expected_revision=saved['revision']))
    with store.connect() as db:
        db.execute('DELETE FROM entries WHERE id=?', ('source',))
    assert not summary_events(store, project)


def test_private_cross_project_and_unshared_sources_never_appear(store, course):
    p = packet(store, course)
    student = course.students[0]
    store.add_entry('secret', student.id, course.sprint, 'journal', 'PRIVATE_JOURNAL', {}, True)
    store.add_entry('other', course.students[-1].id, course.sprint, 'project_update', 'OTHER_PROJECT', {})
    pin = save_pin(store, student.project_id, PinUpdate(pin=ProjectPin(shared=True, goal='Test first',
                   source_url='https://example.slack.com/pin')))
    p = review_packet(store, student.project_id)
    assert 'PRIVATE_JOURNAL' not in str(p) and 'OTHER_PROJECT' not in str(p)
    pin_source = next(e for e in p['evidence'] if e['kind'] == 'pin')
    item = {**draft(p), 'sources': {pin_source['id']: pin_source['fingerprint']}}
    save_summaries(store, student.project_id, SummaryUpdate(summaries=[item]))
    save_pin(store, student.project_id, PinUpdate(expected_revision=pin['revision'], pin=ProjectPin()))
    assert not summary_events(store, course.projects[0])
    item['sources'] = {'owner/secret': 'guess'}
    with pytest.raises(PinConflict):
        save_summaries(store, student.project_id, SummaryUpdate(summaries=[item]))


def test_course_feed_requires_roster_and_only_delivers_summaries(dashboard, store, course):
    client, _ = dashboard
    p = packet(store, course)
    path = PREFIX + '/api/projects/' + course.projects[0].id + '/timeline'
    assert client.get(path).status_code == 401
    seed_session(client, store, course.students[0].slack_id)
    assert client.get(path).json()['events'] == []
    save_summaries(store, course.projects[0].id, SummaryUpdate(summaries=[draft(p)]))
    events = client.get(path).json()['events']
    assert len(events) == 1 and events[0]['kind'] == 'summary'
    assert 'Tested the prototype; launch is still planned.' not in str(events)
    assert events[0]['sources'][0]['url'] == 'https://example.slack.com/source'


def test_retention_removes_summary_text(store, course):
    p = packet(store, course)
    save_summaries(store, course.projects[0].id, SummaryUpdate(summaries=[draft(p)]))
    store.purge((datetime.now(timezone.utc) + timedelta(days=91)).isoformat())
    assert review_packet(store, course.projects[0].id)['summaries'] == []
