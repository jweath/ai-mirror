import base64
import json

import httpx
import pytest

from ai_mirror.cli import new_journal
from ai_mirror.digest import generate
from ai_mirror.evidence import GitHub, collect_github


def test_github_attributes_partner_work_without_inventing_shared_ownership(store, course):
    course.github_enabled = True
    store.save_course(course)
    def handler(request):
        if request.url.path.endswith('/commits'):
            return httpx.Response(200, json=[{'author': {'login': 'example-alex'}, 'sha': 'a'*40,
                                            'commit': {'message': 'Add a prototype'}, 'html_url': 'https://github.com/example/garden/commit/'+'a'*40}])
        return httpx.Response(200, json=[])
    github = GitHub(transport=httpx.MockTransport(handler))
    collect_github(store, github)
    assert len(store.get('evidence/sprint-3/alex')['items']) == 1
    assert store.get('evidence/sprint-3/sam')['items'] == []


def test_github_access_failure_is_a_gap_not_a_student_failure(store, course):
    course.github_enabled = True
    store.save_course(course)
    github = GitHub(transport=httpx.MockTransport(lambda request: httpx.Response(404, json={})))
    result = collect_github(store, github)
    assert result['warnings']
    snapshot = store.get('evidence/sprint-3/alex')
    assert snapshot['warnings'] and snapshot['items'] == []


def test_journal_reads_exact_version():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={'type': 'file', 'encoding': 'base64', 'size': 9,
                                        'content': base64.b64encode(b'My words.').decode()})
    github = GitHub(transport=httpx.MockTransport(handler))
    text, error = github.journal({'repository': 'example/garden', 'sha': 'b'*40, 'path': 'journal/me/reflection.md'})
    assert text == 'My words.' and error is None
    assert 'ref='+'b'*40 in seen[0]


def test_new_journal_preserves_existing_human_writing(tmp_path):
    path = new_journal('alex', 'sprint-3', tmp_path)
    path.write_text('My actual reflection')
    with pytest.raises(FileExistsError):
        new_journal('alex', 'sprint-3', tmp_path)
    assert path.read_text() == 'My actual reflection'
    with pytest.raises(ValueError):
        new_journal('../someone', 'sprint-3', tmp_path)


def test_model_cannot_cite_another_students_evidence(store, settings, monkeypatch):
    from dataclasses import replace
    settings = replace(settings, digest_provider='openai', openai_key='fake', openai_model='test-model')
    store.add_entry('private-alex', 'alex', 'sprint-3', 'exit_ticket', 'My text', {})
    students = [{'student_id': s.id, 'summary': 'Some evidence.', 'feedback': 'What changed?',
                 'source_ids': ['private-alex']} for s in store.course().students]
    def mock(*args, **kwargs):
        assert kwargs['json']['store'] is False
        return httpx.Response(200, json={'output': [{'content': [{'type': 'output_text',
            'text': json.dumps({'students': students, 'themes': []})}]}]})
    monkeypatch.setattr(httpx, 'post', mock)
    with pytest.raises(ValueError, match='another student'):
        generate(store, settings)
    assert store.outbox() == [] and store.digest_list() == []
