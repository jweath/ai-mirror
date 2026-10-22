from dataclasses import replace

import pytest

from ai_mirror.rehearsal import capture_rehearsal, send_rehearsal


class RehearsalSlack:
    def __init__(self, course):
        self.course, self.sent = course, []
        self.members = [course.instructor_slack_ids[0], 'UBOT']
    def call(self, method, payload):
        return {'auth.test': {'team_id': self.course.workspace_id, 'user_id': 'UBOT'},
                'conversations.info': {'channel': {'is_private': True, 'is_member': True}},
                'conversations.members': {'members': self.members}}[method]
    def post(self, payload):
        self.sent.append(payload)
        return {'ts': '1.0001'}


def test_rehearsal_is_scoped_idempotent_and_never_activates_class(settings, store, course):
    settings = replace(settings, sends_enabled=False, rehearsal_channel_id='CTEST')
    slack = RehearsalSlack(course)
    before = len(store.outbox())
    result = send_rehearsal(store, settings, slack)
    assert result['status'] == 'sent' and slack.sent[0]['channel'] == 'CTEST'
    assert send_rehearsal(store, settings, slack) == result and len(slack.sent) == 1
    payload = {'team_id':course.workspace_id, 'event':{'type':'message', 'channel':'CTEST', 'thread_ts':'1.0001', 'ts':'2.0001', 'user':course.students[0].slack_id, 'text':'not allowed'}}
    capture_rehearsal(store, payload)
    assert store.get('instructor_rehearsal')['status'] == 'sent'
    payload['event'].update(user=course.instructor_slack_ids[0],text='Do not retain this private text')
    capture_rehearsal(store, payload)
    state = store.get('instructor_rehearsal')
    assert state['status'] == 'reply_captured' and 'private text' not in str(state)
    assert len(store.outbox()) == before


def test_rehearsal_refuses_student_channel_or_extra_member(settings, store, course):
    slack = RehearsalSlack(course)
    with pytest.raises(ValueError):
        send_rehearsal(store, replace(settings,rehearsal_channel_id=course.projects[0].channel_id), slack)
    slack.members.append(course.students[0].slack_id)
    with pytest.raises(ValueError):
        send_rehearsal(store, replace(settings,rehearsal_channel_id='CTEST'),slack)
    assert not slack.sent and not store.get('instructor_rehearsal')
