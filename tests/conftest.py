import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_mirror.config import Course, Settings
from ai_mirror.slack import SlackError
from ai_mirror.store import Store


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


@pytest.fixture
def course(now):
    data = json.loads(Path('config/course.example.json').read_text())
    data.update(active=True, activated_at=(now - timedelta(hours=1)).isoformat(), activity_source='direct')
    data['meetings'] = [{'id': 'today', 'at': now.isoformat(), 'kind': 'exit_ticket'}]
    return Course.model_validate(data)


@pytest.fixture
def store(tmp_path, course):
    db = Store(str(tmp_path / 'mirror.db'))
    db.save_course(course)
    return db


class FakeSlack:
    def __init__(self):
        self.sent = []
        self.error = None
        self.team_id = 'TDEMO'

    def post(self, payload):
        self.sent.append(payload)
        if self.error:
            raise SlackError(self.error, uncertain=True)
        return {'ok': True, 'ts': f'{len(self.sent)}.000001'}

    def call(self, method, payload):
        if method == 'auth.test':
            return {'team_id': self.team_id}
        if method == 'conversations.info':
            return {'channel': {'is_member': True, 'is_archived': False}}
        raise AssertionError(method)


@pytest.fixture
def slack():
    return FakeSlack()


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / 'mirror.db'), admin_token='a' * 48,
                    slack_token='test-token', slack_signing_secret='test-signing',
                    sends_enabled=True, background_enabled=False)
