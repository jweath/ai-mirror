import json
from datetime import datetime, timedelta, timezone

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey

from ai_mirror.evidence import GitHub


def test_app_tokens_are_read_only_per_repository_and_renewed():
    key = RSAKey.generate_key(2048)
    created = []
    calls = []
    def provider(request):
        calls.append(request)
        if request.url.path.endswith('/installation'):
            claims = jwt.decode(request.headers['authorization'].removeprefix('Bearer '), key, algorithms=['RS256']).claims
            assert claims['iss'] == '123' and claims['exp'] - claims['iat'] <= 600
            return httpx.Response(200, json={'id': 10 if '/alice/' in request.url.path else 20})
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body['permissions'] == {'contents':'read', 'issues':'read'}
            assert len(body['repositories']) == 1
            created.append((request.url.path,body))
            return httpx.Response(201, json={'token':'repo-' + body['repositories'][0], 'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        assert request.headers['authorization'] == 'Bearer repo-' + request.url.path.split('/')[3]
        return httpx.Response(200, json=[])
    github = GitHub(app_id='123', private_key=key.as_pem(private=True).decode(), repositories=['alice/one','bob/two'], transport=httpx.MockTransport(provider))
    assert github.pages('/repos/alice/one/commits') == ([], None)
    assert github.pages('/repos/alice/one/issues') == ([], None)
    assert len(created) == 1
    assert github.pages('/repos/bob/two/issues') == ([], None)
    assert len(created) == 2 and created[-1][0] == '/app/installations/20/access_tokens'
    github.tokens['alice/one'] = ('expired', 0)
    github.pages('/repos/alice/one/commits')
    assert len(created) == 3
    before = len(calls)
    assert github.pages('/repos/stranger/private/commits')[1]
    assert len(calls) == before


def test_uninstalled_public_repository_falls_back_without_personal_credential():
    key = RSAKey.generate_key(2048)
    def provider(request):
        if request.url.path.endswith('/installation'):
            return httpx.Response(404)
        assert not request.headers.get('authorization')
        return httpx.Response(200, json=[])
    github = GitHub('personal-secret', app_id='123',private_key=key.as_pem(private=True).decode(), repositories=['alice/one'],transport=httpx.MockTransport(provider))
    assert github.pages('/repos/alice/one/commits') == ([],None)
