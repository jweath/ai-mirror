"""Explicit, operator-reviewed GitHub-only migration; preserve learning history."""
from __future__ import annotations

import json
import time
from typing import Literal

from pydantic import Field

from .config import Course, StrictModel
from .github_app import repository_name
from .store import content_hash, now_iso, stable_json


class MappingReview(StrictModel):
    student_id: str
    github_login: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')
    repository: str | None = None
    expected_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    actor_slack_id: str = Field(pattern=r'^[UW][A-Z0-9]+$')
    reason: str = Field(min_length=10, max_length=500)
    source_url: str = Field(pattern=r'^https://(?:[A-Za-z0-9-]+\.slack\.com|app\.slack\.com|github\.com)/', max_length=1000)
    reviewed: Literal[True]


def update_mapping(store, review: MappingReview, *, apply=False):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old = json.loads(db.execute("SELECT value FROM settings WHERE key='course'").fetchone()['value'])
        before = Course.model_validate(old)
        if review.actor_slack_id not in before.instructor_slack_ids:
            raise ValueError('A configured course instructor must confirm this mapping')
        if content_hash(old) != review.expected_hash:
            raise ValueError('Course configuration changed; review the current mapping again')
        student = next((s for s in before.students if s.id == review.student_id), None)
        if not student:
            raise ValueError('Student is not in this offering')
        data = before.model_dump(mode='json')
        project = before.project(student)
        changes = {}
        if review.github_login and review.github_login != student.github_login:
            next(s for s in data['students'] if s['id'] == student.id)['github_login'] = review.github_login
            changes['github_login'] = {'before': student.github_login, 'after': review.github_login}
        if review.repository:
            repository = repository_name(review.repository)
            if any(p.id != project.id and p.repository and p.repository.lower() == repository.lower()
                   for p in before.projects):
                raise ValueError('Repository is already assigned to another course project')
            if repository != project.repository:
                next(p for p in data['projects'] if p['id'] == project.id)['repository'] = repository
                changes['repository'] = {'before': project.repository, 'after': repository}
        Course.model_validate(data)  # Includes duplicate personal-account checks.
        result = {'applied': bool(apply and changes), 'student_id': student.id, 'project_id': project.id,
                  'changes': changes, 'course_hash': content_hash(data)}
        if not apply or not changes:
            return result
        # Archive stale views as well as the original course. Entries, journals, pins,
        # submission receipts, digests, and messages are never reassigned or deleted.
        keys = ['github_connection/'+project.id, f'project_evidence/{before.sprint}/{project.id}']
        affected = [s for s in before.students if s.project_id == project.id] if 'repository' in changes else [student]
        keys += [f'evidence/{before.sprint}/{s.id}' for s in affected]
        cache = {}
        for key in keys:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            if row:
                cache[key] = json.loads(row['value'])
                db.execute('DELETE FROM settings WHERE key=?', (key,))
        at = now_iso()
        history = {'course_before': old, 'course_after_hash': content_hash(data), 'archived_views': cache,
                   'review': review.model_dump(mode='json'), 'at': at}
        db.execute('INSERT INTO settings VALUES (?,?)',
                   ('github_mapping_history/'+content_hash(history), stable_json(history)))
        db.execute("UPDATE settings SET value=? WHERE key='course'", (stable_json(data),))
        db.execute('INSERT INTO audit(action,detail,at) VALUES (?,?,?)',
                   ('github_mapping_reviewed', stable_json({**result, 'actor': review.actor_slack_id,
                                                           'source_url': review.source_url, 'reason': review.reason}), at))
        db.execute('CREATE TABLE IF NOT EXISTS github_refresh (project TEXT PRIMARY KEY, changed REAL NOT NULL)')
        db.execute('INSERT INTO github_refresh VALUES (?,?) ON CONFLICT(project) DO UPDATE SET changed=excluded.changed',
                   (project.id, time.time()))
        return result
