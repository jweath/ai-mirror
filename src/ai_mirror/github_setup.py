"""Instructor-owned app registration and course-scoped connection checks."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from joserfc.jwk import RSAKey

from .github_app import READ_PERMISSIONS, AppProvider, GitHubSetupError, credentials
from .store import stable_json


class PrivateQueryFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = str(args[2]).split('?', 1)[0]
            record.args = tuple(args)
        return True


def initialize(store):
    with store.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS github_registration (
            state TEXT PRIMARY KEY, actor TEXT NOT NULL, course TEXT NOT NULL,
            expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS github_delivery (id TEXT PRIMARY KEY, at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS github_refresh (project TEXT PRIMARY KEY, changed REAL NOT NULL);
        ''')


def manifest(settings):
    root = settings.workspace_url.rstrip('/')
    return {'name': 'ENTR Project Reader - jweath', 'url': 'https://jweath.com/entr/',
            'description': 'Read-only project and individual learning-journal evidence for ENTR 5000.',
            'public': True, 'redirect_url': root + '/github/manifest/callback',
            'setup_url': root + '/#setup', 'setup_on_update': True,
            'hook_attributes': {'url': root + '/hooks/github', 'active': True},
            'default_permissions': READ_PERMISSIONS,
            'default_events': ['push', 'issues', 'issue_comment'], 'request_oauth_on_install': False}


def save_credentials(settings, data):
    if type(data.get('id')) is not int or not re.fullmatch(r'[a-z0-9-]+', data.get('slug', '')):
        raise GitHubSetupError('GitHub did not return a valid app registration.')
    perms = data.get('permissions', {})
    if any(perms.get(k) != v for k, v in READ_PERMISSIONS.items()) or any(
        k not in ('contents', 'issues', 'metadata') or v != 'read' for k, v in perms.items()
    ):
        raise GitHubSetupError('The app permissions need instructor review.')
    RSAKey.import_key(data['pem']).as_pem(private=True)
    if not isinstance(data.get('webhook_secret'), str) or len(data['webhook_secret']) < 20:
        raise GitHubSetupError('GitHub did not return a webhook signing secret.')
    value = {k: data[k] for k in ('id', 'slug', 'pem', 'webhook_secret')}
    path = Path(settings.github_app_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(stable_json(value))
        stream.flush()
        os.fsync(stream.fileno())


def connection(store, project):
    saved = store.get('github_connection/' + project.id)
    if not project.repository:
        return {'project_id': project.id, 'project': project.name, 'repository': None,
                'installed': False, 'error': 'Repository link needed.',
                'checked_at': None}
    if not saved or saved.get('repository') != project.repository:
        return {'project_id': project.id, 'project': project.name, 'repository': project.repository,
                'installed': False, 'error': 'Repository access has not been checked yet.', 'checked_at': None}
    return {**saved, 'project_id': project.id, 'project': project.name}


def check_project(store, provider, project):
    now = datetime.now(timezone.utc).isoformat()
    try:
        result = provider.probe(project.repository)
    except GitHubSetupError as exc:
        result = {'installed': False, 'error': str(exc)}
    result.update(repository=project.repository, checked_at=now)
    store.set('github_connection/' + project.id, result)
    return result


def refresh_connections(store, settings, now):
    """At most two probes per tick; webhooks accelerate only mapped repositories."""
    if not credentials(settings):
        return []
    provider, refreshed = AppProvider(settings), []
    course = store.course()
    with store.connect() as db:
        dirty = {r['project']: r['changed'] for r in db.execute('SELECT * FROM github_refresh')}
    for project in sorted(course.projects, key=lambda p: p.id not in dirty):
        if not project.repository:
            continue
        prior = store.get('github_connection/' + project.id, {})
        checked = datetime.fromisoformat(prior['checked_at']).timestamp() if prior.get('checked_at') else 0
        if now.timestamp() - checked < (30 if project.id in dirty else 1800):
            continue
        check_project(store, provider, project)
        refreshed.append(project.id)
        with store.connect() as db:
            db.execute('DELETE FROM github_refresh WHERE project=? AND changed<=?',
                       (project.id, dirty.get(project.id, now.timestamp())))
        if len(refreshed) == 2:
            break
    return refreshed


def install_routes(app, settings, store, shared_session):
    initialize(store)
    provider = AppProvider(settings)
    app.state.github_provider = provider
    prefix = urlsplit(settings.workspace_url).path

    def teacher(user=Depends(shared_session)):
        if not any(g['course'] == '5000' and g['role'] == 'instructor' for g in user['grants']):
            raise HTTPException(403, '5000 instructor access required')
        return user

    def projects(user):
        course = store.course()
        if any(g['course'] == '5000' and g['role'] == 'instructor' for g in user['grants']):
            return course.projects
        student = course.student_by_slack(user['id'])
        if not student or not any(g['course'] == '5000' for g in user['grants']):
            raise HTTPException(403, '5000 enrollment required')
        return [course.project(student)]

    @app.get('/api/github')
    def status(user=Depends(shared_session)):
        selected = projects(user)
        try:
            info = provider.info()
        except GitHubSetupError as exc:
            info = {'configured': False, 'error': str(exc)}
        course = store.course()
        student = course.student_by_slack(user['id'])
        rows = []
        for project in selected:
            row = connection(store, project)
            row['members'] = [{'name': s.name, 'github_login': s.github_login}
                              for s in course.students if s.project_id == project.id]
            rows.append(row)
        return {'app': info, 'projects': rows, 'github_login': student.github_login if student else None,
                'can_register': bool(settings.github_bootstrap_enabled and not credentials(settings)
                                     and user['id'] in course.instructor_slack_ids),
                'guide_url': '/entr/5000/resources/github-setup/'}

    @app.post('/api/github/check/{project_id}')
    def check(project_id: str, user=Depends(shared_session)):
        project = next((p for p in projects(user) if p.id == project_id), None)
        if not project:
            raise HTTPException(404, 'Project not found')
        if not project.repository:
            raise HTTPException(400, 'Send John the repository link in your project Slack channel.')
        prior = connection(store, project)
        if prior.get('checked_at') and time.time()-datetime.fromisoformat(prior['checked_at']).timestamp() < 30:
            return prior
        return check_project(store, provider, project)

    @app.post('/api/github/registration')
    def start(user=Depends(teacher)):
        if not settings.github_bootstrap_enabled or not settings.github_app_config_path:
            raise HTTPException(403, 'App registration is disabled')
        if credentials(settings):
            raise HTTPException(409, 'The course app is already registered')
        state = secrets.token_urlsafe(40)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT 1 FROM github_registration LIMIT 1').fetchone()
            if prior:
                raise HTTPException(409, 'A registration is already in progress. Finish it before starting another.')
            db.execute('INSERT INTO github_registration VALUES (?,?,?,?,0)',
                       (hashlib.sha256(state.encode()).hexdigest(), user['id'], store.course().id, time.time()+3600))
        return {'url': prefix + '/github/register?state=' + state}

    def registration(state, user):
        with store.connect() as db:
            row = db.execute('SELECT * FROM github_registration WHERE state=?',
                             (hashlib.sha256(state.encode()).hexdigest(),)).fetchone()
        if (not row or row['actor'] != user['id'] or row['course'] != store.course().id
                or row['expires'] < time.time() or row['used']):
            raise HTTPException(400, 'Registration expired or already used. Review the existing GitHub app before retrying.')
        return row

    @app.get('/github/register')
    def register(state: str, user=Depends(teacher)):
        registration(state, user)
        if credentials(settings):
            raise HTTPException(409, 'The app is already registered')
        body = html.escape(json.dumps(manifest(settings)), quote=True)
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Register course GitHub app</title><h1>Register ENTR Project Reader</h1>'
            '<p>Read-only Contents, Issues, and repository metadata. Owners select their project repository.</p>'
            '<p>GitHub generates the app credentials and saves them privately in the existing AI Mirror service.</p>'
            '<form method="post" action="https://github.com/settings/apps/new?state='+html.escape(state)+'">'
            '<input type="hidden" name="manifest" value="'+body+'"><button>Review on GitHub</button></form></html>')

    @app.get('/github/manifest/callback')
    def callback(code: str, state: str, user=Depends(teacher)):
        registration(state, user)
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', code) or credentials(settings):
            raise HTTPException(400, 'Invalid or completed registration')
        with store.connect() as db:
            changed = db.execute('UPDATE github_registration SET used=1 WHERE state=? AND used=0',
                                 (hashlib.sha256(state.encode()).hexdigest(),)).rowcount
        if changed != 1:
            raise HTTPException(409, 'Registration was already processed')
        try:
            with httpx.Client(timeout=20, transport=app.state.github_provider.transport) as client:
                response = client.post('https://api.github.com/app-manifests/'+code+'/conversions',
                                       headers={'Accept': 'application/vnd.github+json'})
            if response.status_code != 201:
                raise GitHubSetupError('GitHub registration did not complete. Review the existing app before retrying.')
            save_credentials(settings, response.json())
            store.audit('github_app_registered', {'actor': user['id'], 'app_id': response.json()['id']})
        except Exception:
            # Never disclose code, provider body, or secrets in responses/logs.
            raise HTTPException(502, 'Registration needs instructor attention. Review the existing GitHub app before retrying.') from None
        return RedirectResponse(settings.workspace_url + '/#setup', status_code=303)

    @app.post('/hooks/github')
    async def hook(request: Request):
        config = credentials(settings)
        if not config or not config.get('webhook_secret'):
            raise HTTPException(503, 'GitHub connection is not ready')
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > 1_000_000:
                raise HTTPException(413, 'Body too large')
        expected = 'sha256=' + hmac.new(config['webhook_secret'].encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get('X-Hub-Signature-256', '')):
            raise HTTPException(401, 'Invalid webhook signature')
        delivery = request.headers.get('X-GitHub-Delivery', '')
        if not re.fullmatch(r'[A-Za-z0-9-]{1,100}', delivery):
            raise HTTPException(400, 'Missing delivery identifier')
        try:
            data = json.loads(raw)
        except ValueError:
            raise HTTPException(400, 'Invalid webhook body') from None
        event = request.headers.get('X-GitHub-Event', '')
        names = []
        if isinstance(data, dict):
            repository = data.get('repository')
            names = [repository.get('full_name', '')] if isinstance(repository, dict) else []
            for key in ('repositories', 'repositories_added', 'repositories_removed'):
                rows = data.get(key)
                if isinstance(rows, list):
                    names += [r.get('full_name', '') for r in rows if isinstance(r, dict)]
        names = {str(n).lower() for n in names}
        selected = [p.id for p in store.course().projects if p.repository and p.repository.lower() in names]
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('INSERT OR IGNORE INTO github_delivery VALUES (?,?)', (delivery, time.time())).rowcount:
                return {'accepted': True, 'duplicate': True}
            if event in ('push', 'issues', 'issue_comment', 'installation', 'installation_repositories'):
                for project in selected:
                    db.execute('INSERT INTO github_refresh VALUES (?,?) ON CONFLICT(project) '
                               'DO UPDATE SET changed=excluded.changed', (project, time.time()))
            db.execute('DELETE FROM github_delivery WHERE at<?', (time.time()-7*86400,))
        return {'accepted': True}
