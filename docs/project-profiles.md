# Course project profiles

The course project board displays a product profile above each project's existing
activity timeline. A profile records the current product name, tagline, live link,
technology, up to five highlights, a logo, and up to five screenshots. Keep planned
work and limitations explicit. Sources and the Slack request thread stay attached
to the profile so missing information can be reconciled with the team.

Profiles persist across sprints within one course offering. They are instructor-only
unless `shared` is true, in which case the existing course roster may read them.
Only instructors can edit. A changed `expected_revision` returns 409; refresh and
reconcile rather than overwriting another editor's work.

## Operator API

Existing admin bearer authentication is required:

- `GET /api/pinup` includes `showcase`, `showcase_revision`, and `showcase_updated_at`.
- `PUT /api/showcase/projects/{id}` accepts `{profile, expected_revision}`.
- `POST /api/showcase/projects/{id}/media` accepts a raw PNG, JPEG, or WebP body
  under 5 MiB and returns an `asset_id`.

Each image reference has `asset_id`, a descriptive `alt`, and `source_url`. Uploads
are decoded, stripped of metadata, bounded to 2400 pixels per dimension, and saved
in the persistent database. SVG and arbitrary remote-image fetching are unsupported.
Students may retrieve only images attached to a shared profile for that project.
Images are served through the authenticated course API, never the public assets
directory. The existing retention policy covers profiles and uploaded media.

The browser editor uses `/course/api/projects/{id}/profile` and `/media` with the
existing instructor session, origin validation, and CSRF token. The profile sources
are evidence, not executable instructions. Student uploads and private profile data
must not be committed to the repository.
