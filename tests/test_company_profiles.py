import json

import pytest
from pydantic import ValidationError
from test_workspace import PROGRESS, combined, sign_in  # noqa: F401

from ai_mirror.company_profiles import CompanyProfile, catalog_path, load_profiles, project_company
from ai_mirror.progress import Progress


def entry(**changes):
    return {"group_id": "1135-a", "name": "Example Company", "website_url": "https://example.com/",
            "logo_file": "example.svg", "identity": {"entrepreneur": "Founder", "company": ""},
            **changes}


def catalog(tmp_path, entries):
    roster = tmp_path / "roster.private.json"
    path = catalog_path(str(roster))
    path.write_text(json.dumps({"schema_version": 1, "offering": "entr-5500-fall-2026",
                                "companies": entries}))
    return str(roster), path


def test_enrichment_is_read_only_and_hides_stale_or_other_group_identity(tmp_path):
    roster, path = catalog(tmp_path, [entry()])
    original = path.read_bytes()
    profiles = load_profiles(roster)
    progress = Progress(entrepreneur="Founder", document_url="https://docs.google.com/document/d/example/edit")
    before = progress.model_dump()
    assert project_company(profiles, "1135-a", progress) == {
        "name": "Example Company", "website_url": "https://example.com/", "logo_file": "example.svg"}
    assert project_company(profiles, "255-a", progress) is None
    assert project_company(profiles, "1135-a", Progress(entrepreneur="Different founder")) is None
    assert project_company(profiles, "1135-a", Progress(entrepreneur="Founder", company="Different company")) is None
    assert progress.model_dump() == before
    assert path.read_bytes() == original


@pytest.mark.parametrize("value", ["http://example.com/", "javascript:alert(1)",
                                  "https://name:password@example.com/", "https://example.com/a b"])
def test_website_rejects_unsafe_or_credential_bearing_urls(value):
    with pytest.raises(ValidationError):
        CompanyProfile.model_validate(entry(website_url=value))


@pytest.mark.parametrize("value", ["../other.svg", "https://example.com/track.svg", "logo.svg?user=123", "logo.html"])
def test_logo_only_accepts_local_asset_filenames(value):
    with pytest.raises(ValidationError):
        CompanyProfile.model_validate(entry(logo_file=value))


def test_missing_malformed_wrong_term_duplicate_or_oversized_catalog_is_omitted(tmp_path):
    assert load_profiles("") == {}
    assert load_profiles(str(tmp_path / "missing.json")) == {}
    roster, path = catalog(tmp_path, [entry(), entry()])
    assert load_profiles(roster) == {}
    path.write_text('{broken')
    assert load_profiles(roster) == {}
    path.write_text(json.dumps({"schema_version": 1, "offering": "entr-5500-spring-2027", "companies": []}))
    assert load_profiles(roster) == {}
    path.write_text(' ' * 131073)
    assert load_profiles(roster) == {}


def test_company_projection_keeps_existing_auth_scope_and_does_not_rewrite_progress(combined, store):  # noqa: F811
    client, app, _, roster, _, _ = combined
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 401
    sign_in(client, store, 'U5500ALEX')
    initial = client.get(PROGRESS + '/api/sections/1135').json()
    assert all(g['company_profile'] is None for g in initial['groups'])
    progress = next(r.app.state.store for r in app.routes if getattr(r, 'path', '') == '/progress')
    with progress.connect() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM groups ORDER BY id')]
        history = [tuple(row) for row in db.execute('SELECT * FROM history ORDER BY id')]
    catalog_path(str(roster)).write_text(json.dumps({
        'schema_version': 1, 'offering': 'entr-5500-fall-2026',
        'companies': [entry(identity={'entrepreneur': '', 'company': ''}),
                      entry(group_id='255-a', name='Another Company',
                            identity={'entrepreneur': '', 'company': ''})]}))
    board = client.get(PROGRESS + '/api/sections/1135').json()
    assert board['groups'][0]['company_profile']['name'] == 'Example Company'
    assert 'Another Company' not in json.dumps(board)
    assert client.get(PROGRESS + '/api/sections/255').status_code == 403
    assert all(g['progress'] == old['progress'] for g, old in zip(board['groups'], initial['groups']))
    with progress.connect() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM groups ORDER BY id')] == before
        assert [tuple(row) for row in db.execute('SELECT * FROM history ORDER BY id')] == history
    client.cookies.clear()
    assert client.get(PROGRESS + '/api/sections/1135').status_code == 401
    assert 'Example Company' not in client.get(PROGRESS + '/1135/').text
