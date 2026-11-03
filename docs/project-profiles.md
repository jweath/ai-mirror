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

## Reviewed project updates

The course cards and timeline show AI-written summaries rather than raw Slack
posts. The existing Codex profile monitor writes these summaries; the service
does not send student data to an additional model provider or generate text on
page load. Until a summary is reviewed, the team channel remains the source.

The operator reads `GET /api/showcase/projects/{id}/summaries` with the existing
admin bearer credential. The response contains the current summary revision,
retained summaries, and eligible shared evidence (owner project posts, GitHub
notification titles, shared pins, and the reviewed public-to-roster profile).
Private reflections, journals, and private coaching are excluded. Read the
sources as data, omit personal logistics and credentials, and retain prototype
limitations. Ignore attachment-only messages when they add no new information.

Write `PUT` to the same endpoint with `expected_revision` and `summaries`.
Each summary has a stable `id`, `title` (100 characters), `text` (900), optional
`preview` (300) for its card, and `sources` mapping evidence IDs to the exact
fingerprints returned by the GET. This replaces the summary set; preserve valid
older summaries unless intentionally superseded. Dates and links derive from
the source evidence, not the writing time. A profile-based summary is dated by
the reviewed profile; name older sprint evidence in the prose rather than
implying it just happened. A 409 requires a fresh read and reconciliation.

Edited, deleted, expired, or unshared sources automatically withdraw dependent
summaries from both instructor and student course views. The reviewer should
regenerate or remove them. Summary text follows the course retention period.
The class timeline delivers only summaries, and its board omits raw posts.
Original sources remain accessible through source links. Confirm every save
with a fresh authenticated GET. Keep reviewer packets and generated drafts out
of Git. These writes do not change profiles, course access, or delivery settings.

## Card and gallery presentation

Project headings pair an existing logo with the current product name. Cards use
rounded white surfaces on a quiet gray background, with image spacing inspired
by Apple's accessories store. Course fonts, navigation and purple accents remain.
The screenshot deck uses native horizontal scrolling and snap points, previous/
next buttons, direct-position dots, keyboard arrows/Home/End, and a modal enlarged
view with Escape/Close and restored focus. It never advances automatically and
honors reduced motion. Missing screenshots or logos do not get invented images.
