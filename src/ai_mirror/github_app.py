"""GitHub App credentials and bounded read operations; never return secrets to UI."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey

READ_PERMISSIONS = {"contents": "read", "issues": "read"}


class GitHubSetupError(ValueError):
    pass


def credentials(settings):
    if settings.github_app_id and settings.github_app_private_key:
        return {"id": str(settings.github_app_id), "pem": settings.github_app_private_key,
                "slug": settings.github_app_slug, "webhook_secret": settings.github_webhook_secret}
    path = Path(settings.github_app_config_path) if settings.github_app_config_path else None
    if path and path.exists():
        try:
            if path.stat().st_mode & 0o077:
                raise ValueError("Private configuration permissions")
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or not value.get("id") or not value.get("pem"):
                raise ValueError("Incomplete configuration")
            return value
        except (OSError, ValueError, TypeError):
            raise GitHubSetupError("The GitHub App configuration needs instructor attention.") from None
    if settings.github_app_id or settings.github_app_private_key:
        raise GitHubSetupError("The GitHub App configuration is incomplete.")
    return None


def assertion(config):
    now = int(time.time())
    key = RSAKey.import_key(config['pem'])
    return jwt.encode({"alg": "RS256"}, {"iat": now-60, "exp": now+540, "iss": str(config['id'])}, key)


def repository_name(value):
    value = value.strip().removesuffix('/')
    if value.startswith('https://github.com/'):
        value = value.removeprefix('https://github.com/')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', value):
        raise GitHubSetupError('Use the project repository link, such as https://github.com/owner/project.')
    if value.split('/')[1] in ('.', '..'):
        raise GitHubSetupError('Use a project repository link.')
    return value


class AppProvider:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    def call(self, method, path, *, token=None, body=None, app=True):
        config = credentials(self.settings)
        if app and not config:
            raise GitHubSetupError('The instructor is finishing GitHub setup.')
        headers = {'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28',
                   'User-Agent':'ENTR-Course-Workspace'}
        try:
            auth = assertion(config) if app else token
        except Exception:
            raise GitHubSetupError('The GitHub App signing key needs instructor attention.') from None
        if app:
            headers['Authorization'] = 'Bearer '+auth
        elif token:
            headers['Authorization'] = 'Bearer '+token
        try:
            with httpx.Client(base_url='https://api.github.com',timeout=10,transport=self.transport,
                              follow_redirects=False,headers=headers) as client:
                return client.request(method,path,json=body)
        except Exception:
            # Provider exceptions can include bearer credentials and temporary codes.
            raise GitHubSetupError('GitHub could not be reached. Try again shortly.') from None

    def info(self):
        if not credentials(self.settings):
            return {'configured':False,'error':None}
        result = self.call('GET','/app')
        if result.status_code != 200:
            return {'configured':False,'error':'GitHub could not verify the course app.'}
        data = result.json()
        permissions = data.get('permissions',{})
        if (any(permissions.get(k) != v for k,v in READ_PERMISSIONS.items())
                or any(v not in ('read',None) or k not in ('contents','issues','metadata')
                       for k,v in permissions.items())):
            return {'configured':False,'error':'The course app permissions need instructor review.'}
        slug = data.get('slug','')
        if not re.fullmatch(r'[a-z0-9-]+',slug):
            return {'configured':False,'error':'GitHub did not return a valid installation link.'}
        return {'configured':True,'id':str(data['id']),'name':data['name'],'slug':slug,
                'install_url':'https://github.com/apps/'+slug+'/installations/new',
                'permissions':permissions,'error':None}

    def probe(self, repository, *, public_metadata=False):
        repository = repository_name(repository)
        result = self.call('GET',f'/repos/{repository}/installation')
        if result.status_code == 404:
            if public_metadata:
                response = self.call('GET',f'/repos/{repository}',app=False)
                if response.status_code == 200:
                    data = response.json()
                    return {'installed':False,'metadata':self.metadata(data),'error':'The owner needs to install the course app on this repository.'}
            return {'installed':False,'error':'The owner needs to install the course app on this repository, or confirm its link.'}
        if result.status_code != 200:
            raise GitHubSetupError('GitHub could not check this repository. Try again shortly.')
        installation = result.json()
        permissions = installation.get('permissions',{})
        if any(permissions.get(k) != v for k,v in READ_PERMISSIONS.items()):
            return {'installed':False,'error':'The installed app needs the expected read-only Contents and Issues permissions.'}
        minted = self.call('POST',f"/app/installations/{int(installation['id'])}/access_tokens",
                          body={'repositories':[repository.split('/')[1]],'permissions':READ_PERMISSIONS})
        if minted.status_code != 201:
            raise GitHubSetupError('GitHub did not authorize a read-only repository connection.')
        token = minted.json().get('token')
        if not token:
            raise GitHubSetupError('GitHub did not return a repository connection.')
        response = self.call('GET',f'/repos/{repository}',token=token,app=False)
        if response.status_code != 200:
            raise GitHubSetupError('The repository link could not be verified. Check its current name.')
        data = response.json()
        metadata = self.metadata(data)
        return {'installed':True,'installation_id':installation['id'],'metadata':metadata,
                'issues_enabled':bool(data.get('has_issues')),
                'error':None if data.get('has_issues') else 'Enable Issues in the repository settings for journal submission receipts.'}

    @staticmethod
    def metadata(data):
        repository = repository_name(data['full_name'])
        if type(data.get('id')) is not int:
            raise GitHubSetupError('GitHub did not identify the repository.')
        return {'id':data['id'],'repository':repository,'url':'https://github.com/'+repository,
                'private':bool(data.get('private')),'issues_enabled':bool(data.get('has_issues'))}

    def profile(self, login):
        login = login.strip().removeprefix('@')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',login):
            raise GitHubSetupError('Enter your GitHub username, not your name or email address.')
        response = self.call('GET','/users/'+login,app=False)
        if response.status_code != 200:
            raise GitHubSetupError('That GitHub username could not be found. Check the spelling.')
        data = response.json()
        if data.get('type') != 'User' or type(data.get('id')) is not int:
            raise GitHubSetupError('Use your individual GitHub account, not an organization account.')
        return {'id':data['id'],'login':data['login'],'url':'https://github.com/'+data['login']}
