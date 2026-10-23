import hashlib
import hmac
import json
import logging
import stat
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc.jwk import RSAKey
from test_workspace import HEADERS, WORKSPACE, combined, sign_in

from ai_mirror.github_app import AppProvider, GitHubSetupError, credentials, repository_name
from ai_mirror.github_setup import PrivateQueryFilter, manifest, refresh_connections, save_credentials

__all__ = ['combined']


@pytest.fixture
def github(combined, tmp_path):
    client, app, config, *_ = combined
    object.__setattr__(config, 'github_bootstrap_enabled', True)
    object.__setattr__(config, 'github_app_config_path', str(tmp_path / 'app.private.json'))
    key = RSAKey.generate_key(2048)
    data = {'id': 123, 'slug': 'entr-project-reader-jweath', 'pem': key.as_pem(private=True).decode(),
            'webhook_secret': 'test-hook-'+'s'*32, 'permissions': {'contents': 'read', 'issues': 'read', 'metadata': 'read'},
            'name': 'ENTR Project Reader', 'client_secret': 'unused-must-not-persist'}
    return client, app, config, data


def start(github, store, course):
    client, *_ = github
    sign_in(client, store, course.instructor_slack_ids[0])
    result = client.post(WORKSPACE+'/api/github/registration', headers=HEADERS)
    assert result.status_code == 200
    return parse_qs(urlsplit(result.json()['url']).query)['state'][0]


def test_student_project_scope_and_csrf(github, store, course):
    client, _, _, _ = github
    assert client.get(WORKSPACE+'/api/github').status_code == 401
    sign_in(client, store, 'U5500ALEX')
    assert client.get(WORKSPACE+'/api/github').status_code == 403
    assert client.post(WORKSPACE+'/api/github/registration', headers=HEADERS).status_code == 403
    student = course.students[0]
    sign_in(client, store, student.slack_id)
    result = client.get(WORKSPACE+'/api/github').json()
    assert [p['project_id'] for p in result['projects']] == [student.project_id]
    assert not result['can_register']
    assert client.post(WORKSPACE+'/api/github/registration', headers=HEADERS).status_code == 403
    assert client.post(WORKSPACE+'/api/github/check/stranger', headers=HEADERS).status_code == 404
    assert client.post(WORKSPACE+'/api/github/check/'+student.project_id).status_code == 403


def test_registration_single_use_and_private_credentials(github, store, course):
    client, app, config, data = github
    state = start(github, store, course)
    assert client.post(WORKSPACE+'/api/github/registration', headers=HEADERS).status_code == 409
    page = client.get(WORKSPACE+'/github/register', params={'state': state})
    assert 'Review on GitHub' in page.text and data['pem'] not in page.text
    assert manifest(config)['default_permissions'] == {'contents': 'read', 'issues': 'read'}
    assert manifest(config)['request_oauth_on_install'] is False
    calls = []
    def provider(request):
        calls.append(request)
        assert request.url.host == 'api.github.com'
        return httpx.Response(201, json=data)
    app.state.workspace.state.github_provider.transport = httpx.MockTransport(provider)
    params = {'code': 'one-use-provider-code', 'state': state}
    assert client.get(WORKSPACE+'/github/manifest/callback', params={**params, 'state': 'wrong'}).status_code == 400
    response = client.get(WORKSPACE+'/github/manifest/callback', params=params)
    assert response.status_code == 303
    assert len(calls) == 1
    path = __import__('pathlib').Path(config.github_app_config_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'client_secret' not in path.read_text()
    assert credentials(config)['id'] == 123
    assert client.get(WORKSPACE+'/github/manifest/callback', params=params).status_code == 400
    with pytest.raises(FileExistsError):
        save_credentials(config, data)
    with store.connect() as db:
        saved = str([tuple(r) for r in db.execute('SELECT * FROM audit')])
    assert data['pem'] not in saved and data['webhook_secret'] not in saved


def test_registration_expiry_actor_and_unknown_outcome(github, store, course):
    client, app, config, _ = github
    state = start(github, store, course)
    app.state.workspace.state.github_provider.transport = httpx.MockTransport(lambda req: httpx.Response(503))
    result = client.get(WORKSPACE+'/github/manifest/callback', params={'state': state, 'code': 'one-use-provider-code'})
    assert result.status_code == 502 and 'Review the existing' in result.json()['detail']
    assert credentials(config) is None
    assert client.post(WORKSPACE+'/api/github/registration', headers=HEADERS).status_code == 409
    assert client.get(WORKSPACE+'/github/register', params={'state': state}).status_code == 400


def test_webhook_auth_deduplication_and_repository_allowlist(github, store, course):
    client, _, config, data = github
    save_credentials(config, data)
    project = next(p for p in course.projects if p.repository)
    def send(payload, delivery='delivery-one', signature=True):
        raw = json.dumps(payload).encode()
        digest = hmac.new(data['webhook_secret'].encode(), raw, hashlib.sha256).hexdigest()
        return client.post(WORKSPACE+'/hooks/github', content=raw, headers={
            'X-GitHub-Delivery': delivery, 'X-GitHub-Event': 'push',
            'X-Hub-Signature-256': 'sha256='+digest if signature else 'wrong'})
    assert send({'repository': {'full_name': project.repository}}, signature=False).status_code == 401
    assert send({'repository': {'full_name': 'stranger/private'}}, delivery='outside').status_code == 200
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM github_refresh').fetchone()[0] == 0
    payload = {'repository': {'full_name': project.repository}, 'commits': [{'message': 'private-text-never-save'}]}
    assert send(payload).status_code == 200
    assert send(payload).json()['duplicate'] is True
    with store.connect() as db:
        assert [r['project'] for r in db.execute('SELECT * FROM github_refresh')] == [project.id]
        assert 'private-text-never-save' not in str([tuple(r) for r in db.execute('SELECT * FROM github_delivery')])


def test_read_only_repository_tokens_and_revocation(github):
    _, _, config, data = github
    save_credentials(config, data)
    calls = []
    def provider(request):
        calls.append(request)
        if request.url.path == '/app':
            return httpx.Response(200, json=data)
        if request.url.path.endswith('/installation'):
            return httpx.Response(200, json={'id': 88, 'permissions': data['permissions']})
        if request.method == 'POST':
            assert json.loads(request.content) == {'repositories': ['project'], 'permissions': {'contents': 'read', 'issues': 'read'}}
            return httpx.Response(201, json={'token': 'repo-scoped-token'})
        assert request.headers['Authorization'] == 'Bearer repo-scoped-token'
        return httpx.Response(200, json={'id': 99, 'full_name': 'owner/project', 'private': True, 'has_issues': True})
    api = AppProvider(config, httpx.MockTransport(provider))
    assert api.info()['configured']
    assert api.probe('owner/project')['installed']
    api.transport = httpx.MockTransport(lambda req: httpx.Response(404))
    result = api.probe('owner/project')
    assert not result['installed'] and 'owner needs to install' in result['error']
    data['permissions']['contents'] = 'write'
    api.transport = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    assert not api.info()['configured']


def test_refresh_is_bounded_and_does_not_overwrite_full_scan(github, store, monkeypatch, now):
    _, _, config, data = github
    save_credentials(config, data)
    store.set('last_github_collection', {'at': 'prior-full-scan'})
    calls = []
    def probe(self, repository):
        calls.append(repository)
        return {'installed': False, 'error': 'installation removed'}
    monkeypatch.setattr(AppProvider, 'probe', probe)
    assert refresh_connections(store, config, now) == []
    assert len(calls) == 2
    assert store.get('last_github_collection')['at'] == 'prior-full-scan'
    assert sum(bool(store.get('github_connection/'+p.id)) for p in store.course().projects) == 2


def test_config_fail_closed_and_query_redaction(github):
    _, _, config, _ = github
    object.__setattr__(config, 'github_app_id', '123')
    with pytest.raises(GitHubSetupError):
        credentials(config)
    for value in ('https://evil.example/owner/repo', '../repo', 'owner/repo?token=secret', 'owner/..'):
        with pytest.raises(GitHubSetupError):
            repository_name(value)
    record = logging.LogRecord('uvicorn.access', 20, '', 0, '%s %s %s %s %s',
                               ('client', 'GET', '/callback?code=secret&state=hidden', '1.1', 200), None)
    assert PrivateQueryFilter().filter(record)
    assert 'secret' not in record.getMessage() and '/callback' in record.getMessage()


def test_partial_environment_does_not_fall_back_to_recovery_file(github):
    _, _, config, data = github
    save_credentials(config, data)
    object.__setattr__(config, 'github_app_id', 'wrong-partial-app')
    with pytest.raises(GitHubSetupError, match='incomplete'):
        credentials(config)


def test_malformed_signature_is_rejected_without_server_error(github):
    client, _, config, data = github
    save_credentials(config, data)
    response = client.post(WORKSPACE+'/hooks/github', content=b'{}',
                           headers=[(b'X-Hub-Signature-256', b'\xff'), (b'X-GitHub-Delivery', b'invalid-signature')])
    assert response.status_code == 401


@pytest.mark.parametrize('installed', [True, False])
def test_changed_repositories_refresh_without_turning_health_checks_into_scans(github, store, course, monkeypatch, now, installed):
    _, _, config, data = github
    save_credentials(config, data)
    project = course.projects[0]
    if not installed:
        with store.connect() as db:
            db.execute('INSERT INTO github_refresh VALUES (?,?)', (project.id, now.timestamp()))
    monkeypatch.setattr(AppProvider, 'probe', lambda self, repository: {'installed': installed, 'issues_enabled': installed})
    refreshed = refresh_connections(store, config, now)
    assert project.id in refreshed
    assert len(refreshed) <= 2
    assert refresh_connections(store, config, now) == ([course.projects[2].id] if installed else [])
