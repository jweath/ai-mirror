"""Reviewed AI summaries of shared project evidence, never raw chat in the feed."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import Field, field_validator

from .activity import paginate, project_activity
from .config import StrictModel
from .store import content_hash


class SummaryDraft(StrictModel):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,79}$')
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=900)
    preview: str = Field(default='', max_length=300)
    sources: dict[str, str] = Field(min_length=1, max_length=30)

    @field_validator('title', 'text')
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError('Summary text cannot be blank')
        return value.strip()


class SummaryUpdate(StrictModel):
    summaries: list[SummaryDraft] = Field(max_length=120)
    expected_revision: str | None = None


def project_for(store, project_id):
    course = store.course()
    project = next((p for p in course.projects if p.id == project_id), None) if course else None
    if not project:
        raise KeyError(project_id)
    return project


def evidence(store, project, now=None, entries=None):
    # Both roles use the shared projection. Private coaching/reflections are never summary inputs.
    from .showcase import saved_profile
    events = project_activity(store, project, shared=True, now=now, entries=entries)
    profile = saved_profile(store, project.id, shared=True)
    if profile:
        p = profile['profile']
        events.append({'id': 'profile/' + project.id, 'kind': 'profile', 'at': profile['updated_at'],
                       'title': p['name'] or project.name, 'profile': p,
                       'url': (p.get('sources') or [{}])[0].get('url')})
    return {e['id']: {**e, 'fingerprint': content_hash(e)} for e in events}


def key_for(store, project_id):
    return f'project_summaries/{store.course().sprint}/{project_id}'


def review_packet(store, project_id):
    project = project_for(store, project_id)
    saved = store.get(key_for(store, project_id))
    return {'project_id': project_id, 'revision': content_hash(saved) if saved else None,
            'summaries': saved['summaries'] if saved else [],
            'evidence': list(evidence(store, project).values())}


def valid_summary(item, sources):
    return bool(item['sources']) and all(
        sid in sources and sources[sid]['fingerprint'] == fingerprint
        for sid, fingerprint in item['sources'].items())


def summary_events(store, project, now=None, entries=None):
    from .pinup import safe_url
    sources = evidence(store, project, now, entries)
    saved = store.get(key_for(store, project.id), {})
    result = []
    for item in saved.get('summaries', []):
        # Edits, deletions, expiration and unsharing withdraw dependent summaries immediately.
        if not valid_summary(item, sources):
            continue
        links = []
        for sid in item['sources']:
            source = sources[sid]
            candidates = source['profile'].get('sources', []) if source['kind'] == 'profile' else [{'url': source.get('url')}]
            for candidate in candidates:
                try:
                    url = safe_url(candidate.get('url'))
                except ValueError:
                    url = None
                if url and not any(s['url'] == url for s in links):
                    links.append({'url': url, 'label': 'Product profile source' if source['kind'] == 'profile'
                              else 'GitHub via Slack' if source['kind'] == 'github' else 'Slack source'})
        result.append({'id': 'summary/' + item['id'], 'kind': 'summary', 'at': item['at'],
                       'title': item['title'], 'text': item['text'], 'preview': item.get('preview', ''), 'sources': links})
    return sorted(result, key=lambda item: (item['at'], item['id']), reverse=True)


def summary_timeline(store, project, cursor=None):
    return paginate(summary_events(store, project), cursor)


def save_summaries(store, project_id, update):
    from .pinup import PinConflict
    project = project_for(store, project_id)
    sources = evidence(store, project)
    items = [item.model_dump() for item in update.summaries]
    if len({item['id'] for item in items}) != len(items):
        raise ValueError('Summary IDs must be unique')
    if not all(valid_summary(item, sources) for item in items):
        raise PinConflict('Source evidence changed. Read and reconcile it before saving summaries.')
    for item in items:
        item['at'] = max(sources[sid]['at'] for sid in item['sources'])
    value = {'summaries': items, 'updated_at': datetime.now(timezone.utc).isoformat()}
    key = key_for(store, project_id)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        revision = content_hash(json.loads(previous['value'])) if previous else None
        if revision != update.expected_revision:
            raise PinConflict('Summaries changed. Refresh and reconcile before saving.')
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
    store.audit('project_summaries_updated', {'project_id': project_id, 'count': len(items)})
    return {**value, 'revision': content_hash(value)}
