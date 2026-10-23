import pytest

from ai_mirror.github_mapping import MappingReview, update_mapping
from ai_mirror.store import content_hash


def review(course, **fields):
    return MappingReview(student_id=course.students[0].id, github_login='new-confirmed-account',
                         expected_hash=content_hash(course.model_dump(mode='json')),
                         actor_slack_id=course.instructor_slack_ids[0], reason='Instructor confirmed the student account in Slack.',
                         source_url='https://example.slack.com/archives/CPROJECT/p12345', reviewed=True, **fields)


def test_explicit_migration_preserves_records_and_archives_mapping(store, course):
    student = course.students[0]
    store.add_entry('receipt', student.id, course.sprint, 'submission', 'Original record', {'repository': 'old/project'})
    store.set('github_connection/'+student.project_id, {'installed': True, 'repository': 'old/project'})
    request = review(course, repository='new-owner/project')
    result = update_mapping(store, request)
    assert not result['applied'] and store.course() == course
    result = update_mapping(store, request, apply=True)
    assert result['applied'] and store.course().student_by_slack(student.slack_id).github_login == 'new-confirmed-account'
    assert store.course().student_by_slack(student.slack_id).project_id == student.project_id
    assert store.entries(course.sprint, student.id)[0]['source']['repository'] == 'old/project'
    assert store.get('github_connection/'+student.project_id) is None
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'github_mapping_history/%'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit WHERE action='github_mapping_reviewed'").fetchone()[0] == 1
    with pytest.raises(ValueError, match='changed'):
        update_mapping(store, request, apply=True)


def test_migration_rejects_non_instructor_and_duplicate_accounts(store, course):
    request = review(course)
    with pytest.raises(ValueError, match='instructor'):
        update_mapping(store, request.model_copy(update={'actor_slack_id': course.students[0].slack_id}), apply=True)
    other = next(s for s in course.students[1:] if s.github_login)
    with pytest.raises(ValueError, match='duplicate'):
        update_mapping(store, request.model_copy(update={'github_login': other.github_login}), apply=True)
    assert store.course() == course


def test_migration_rejects_duplicate_repository_and_roster_fields(store, course):
    student = course.students[0]
    other = next(p for p in course.projects if p.id != student.project_id and p.repository)
    with pytest.raises(ValueError, match='another'):
        update_mapping(store, review(course, repository=other.repository), apply=True)
    with pytest.raises(ValueError):
        MappingReview.model_validate({**review(course).model_dump(), 'slack_id': 'USTRANGER'})
    assert store.course() == course
