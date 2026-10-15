from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from ai_mirror.config import Course, Project, Student
from ai_mirror.workflow import (
    deliver_one,
    enqueue_due,
    handle_command,
    handle_event,
    parse_submission,
    peer_rotation,
    plan,
)


def test_schedule_groups_partners_but_requests_individual_replies(course, now):
    jobs = plan(course, now)
    assert len(jobs) == 3
    garden = next(j for j in jobs if j['payload']['channel'] == 'CGARDEN')
    assert '<@UALEX>' in garden['payload']['text'] and '<@USAM>' in garden['payload']['text']


def test_no_backfill_and_no_activation_history(course, now):
    course.meetings[0].at = now - timedelta(hours=2)
    assert plan(course, now) == []
    course.meetings[0].at = now - timedelta(minutes=5)
    course.activated_at = now
    assert plan(course, now) == []


def test_dst_uses_explicit_offset(course, now):
    from datetime import datetime, timezone
    course.meetings[0].at = datetime.fromisoformat('2026-11-03T14:35:00-05:00')
    course.activated_at = datetime.fromisoformat('2026-10-15T00:00:00-04:00')
    jobs = plan(course, datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert jobs[0]['due_at'] == '2026-11-03T19:35:00+00:00'


def test_duplicate_ticks_queue_and_send_once(store, settings, slack, now):
    assert enqueue_due(store, now) == 3
    assert enqueue_due(store, now) == 0
    for _ in range(4):
        deliver_one(store, settings, slack, now)
    assert len(slack.sent) == 3
    assert all(r['status'] == 'sent' for r in store.outbox())


def test_claim_is_exclusive(store, now):
    enqueue_due(store, now)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda _: store.claim(now.isoformat()), range(8)))
    ids = [r['id'] for r in rows if r]
    assert len(ids) == len(set(ids)) == 3


def test_uncertain_delivery_never_automatically_retries(store, settings, slack, now):
    enqueue_due(store, now)
    slack.error = 'timeout'
    for _ in range(6):
        deliver_one(store, settings, slack, now)
    assert len(slack.sent) == 3
    assert all(r['status'] == 'uncertain' for r in store.outbox())


def test_restart_and_hold_fence_delivery(store, settings, slack, now):
    enqueue_due(store, now)
    store.claim(now.isoformat())
    store.recover()
    assert sum(r['status'] == 'uncertain' for r in store.outbox()) == 1
    store.set('delivery_hold', True)
    assert deliver_one(store, settings, slack, now) is None
    assert not slack.sent


def test_disabled_sender_keeps_pending(store, settings, slack, now):
    from dataclasses import replace
    enqueue_due(store, now)
    assert deliver_one(store, replace(settings, sends_enabled=False), slack, now) is None
    assert all(r['status'] == 'pending' for r in store.outbox())


def test_peer_rotation_19_students_one_partner_project(course):
    course.students = [Student(id=f's{i}', name=f'Student {i}', slack_id=f'U{i}', github_login=f's{i}',
                               project_id=f'p{max(i, 1)}') for i in range(19)]
    course.projects = [Project(id=f'p{i}', name=f'Project {i}', channel_id=f'C{i}', repository=f'example/p{i}')
                       for i in range(1, 19)]
    pairs = peer_rotation(course, 'one')
    assert len(pairs) == len(set(a for a, _ in pairs)) == len(set(b for _, b in pairs)) == 19
    by_id = {s.id: s for s in course.students}
    assert all(by_id[a].project_id != by_id[b].project_id for a, b in pairs)
    assert pairs == peer_rotation(course, 'one')
    later = peer_rotation(course, 'two', pairs)
    assert not set(pairs).intersection(later)


def test_impossible_peer_roster_explained(course):
    course.students = course.students[:2]
    with pytest.raises(ValueError, match='No partner-free'):
        peer_rotation(course, 'one')


def event(user='UALEX', channel='CGARDEN', ts='10.000001', thread='1.000001', text='I changed my test.'):
    return {'team_id': 'TDEMO', 'event': {'type': 'message', 'channel': channel, 'user': user,
                                        'ts': ts, 'thread_ts': thread, 'text': text}}


def test_only_registered_owner_in_known_prompt_thread_is_captured(store):
    store.add_prompt('CGARDEN', '1.000001', 'today', 'sprint-3')
    assert handle_event(store, event()) == 'recorded'
    assert handle_event(store, event(user='USAM', ts='11.000001')) == 'recorded'
    assert handle_event(store, event(user='ULEE', ts='12.000001')) == 'ignored'
    assert handle_event(store, event(thread='unrelated')) == 'ignored'
    assert handle_event(store, {**event(), 'team_id': 'TOTHER'}) == 'ignored'
    assert len(store.entries('sprint-3')) == 2


def test_event_retry_edit_and_delete(store):
    store.add_prompt('CGARDEN', '1.000001', 'today', 'sprint-3')
    handle_event(store, event())
    handle_event(store, event())
    assert len(store.entries('sprint-3')) == 1
    edit = {'team_id': 'TDEMO', 'event': {'type': 'message', 'subtype': 'message_changed', 'channel': 'CGARDEN',
                                       'message': event(text='I am still unsure.')['event']}}
    handle_event(store, edit)
    assert store.entries('sprint-3')[0]['text'] == 'I am still unsure.'
    handle_event(store, {'team_id': 'TDEMO', 'event': {'type': 'message', 'subtype': 'message_deleted',
                                                    'channel': 'CGARDEN', 'deleted_ts': '10.000001'}})
    assert not store.entries('sprint-3')


def test_private_muddy_command_does_not_echo_or_post(store):
    result = handle_command(store, {'team_id': 'TDEMO', 'user_id': 'UALEX', 'channel_id': 'COTHER',
                                    'trigger_id': 'unique', 'text': 'muddy I have a private concern.'})
    assert result['response_type'] == 'ephemeral'
    assert 'private concern' not in result['text']
    assert store.entries('sprint-3')[0]['private'] == 1
    assert store.outbox() == []


def test_exit_command_channel_and_markup_boundaries(store):
    form = {'team_id': 'TDEMO', 'user_id': 'UALEX', 'channel_id': 'COTHER',
            'trigger_id': 'unique', 'text': 'exit <!channel> please read'}
    assert handle_command(store, form)['response_type'] == 'ephemeral'
    assert not store.entries('sprint-3')
    form['channel_id'] = 'CGARDEN'
    result = handle_command(store, form)
    assert result['response_type'] == 'in_channel'
    assert '<!channel>' not in result['text']
    assert store.entries('sprint-3')[0]['text'] == '<!channel> please read'


@pytest.mark.parametrize('url', [
    'https://github.com/example/garden/blob/main/journal.md',
    'https://github.com/other/garden/blob/' + 'a'*40 + '/journal.md',
    'https://evil.example/example/garden/blob/' + 'a'*40 + '/journal.md',
    'https://github.com/example/garden/blob/' + 'a'*40 + '/../journal.md',
])
def test_submission_rejects_moving_wrong_repo_and_invalid_links(url):
    with pytest.raises(ValueError):
        parse_submission(url, 'example/garden')


def test_exact_submission_with_issue():
    source = parse_submission('https://github.com/example/garden/blob/' + 'a'*40 +
                              '/journal/alex/sprint-3/reflection.md https://github.com/example/garden/issues/4',
                              'example/garden')
    assert source['sha'] == 'a'*40 and source['issue_url'].endswith('/4')


def test_course_rejects_duplicate_ids_and_naive_dates(course):
    value = course.model_dump(mode='json')
    value['students'][1]['slack_id'] = value['students'][0]['slack_id']
    with pytest.raises(ValueError, match='duplicate Slack'):
        Course.model_validate(value)
    value = course.model_dump(mode='json')
    value['meetings'][0]['at'] = '2026-10-15T14:35:00'
    with pytest.raises(ValueError, match='UTC offset'):
        Course.model_validate(value)
