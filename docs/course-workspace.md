# Shared course workspace

The course workspace provides one Slack sign-in, an enrolled-student home, and a private instructor overview for Fall 2026. It runs in the existing AI Mirror process. The 5500 milestones reuse the reviewed group-progress implementation, with shared identity instead of an independent login or service.

## Public routes and record ownership

| Public URL | Purpose | Record owner |
| --- | --- | --- |
| `/entr/workspace/` | Enrolled courses, current coursework, team/work links | Read-through course directory and published site |
| `/entr/instructor/` | Exceptions, recent changes, projects, people and connections | Instructor-scoped projections of source records |
| `/entr/5000/2026/fall/` | Existing 5000 project overview | Existing Mirror database and course map |
| `/entr/5000/2026/fall/instructor` | 5000 private digests, scheduling and delivery controls | Existing Mirror operator workflow |
| `/entr/5500/2026/fall/1135/` | Morning group milestones | Separate 5500 SQLite database |
| `/entr/5500/2026/fall/255/` | Afternoon group milestones | The same 5500 store, section-scoped |

The Astro site remains static. Caddy routes authenticated paths to this service and publishes `/entr/course-context.json` from the same reviewed brief used by the course homes. Assignment instructions and dates are not edited in this service. Expired or unavailable briefs link back to the course site without inventing deadlines.

Slack conversations, original Docs and repositories, local recordings, attendance corrections, and official grades retain their existing owners. This release adds no AI provider, whole-chat ingestion, grades, class messages, or duplicate deliverable upload. Participation grades/corrections and reminder controls remain in instOS; the workspace explicitly identifies its enrollment input as a dated snapshot, not a live attendance connection.

## Identity and authorization

The existing Slack OIDC callback remains `/entr/5000/2026/fall/auth/callback`. Return destinations are fixed allowlisted values, not arbitrary URLs. Authlib checks signature, issuer, audience, nonce, expiry and browser state; the workspace ID must match the registered course workspace. Provider tokens are not persisted.

The opaque, server-side browser session cookie is Secure, HttpOnly, SameSite=Lax and scoped to `/entr/`. A successful new login deletes the older path-scoped cookie. A pre-existing 5000 session may need one Slack sign-in to obtain the shared cookie. Logout revokes the server-side session across all views. Mutations require the same origin and CSRF token.

Every request resolves current source grants by exact Slack ID. A 5000 instructor is not implicitly a 5500 instructor. An enrolled 5500 student can view only their section and edit only their mapped group. Enrollment without a group permits section viewing and no group editing. Names never establish identity or group membership. Instructor verification and presentation assignment remain instructor-only. Updates use revisions and preserve history; an old scheduled interview date never implies completion.

The private directory joins source IDs under `slack:<member-id>` and includes explicit offering, section and group IDs. Existing 5000 student/project IDs remain intact. The 5500 offering is `entr-5500-fall-2026`; use a term-specific database path. This is an explicit current-term integration, not an automatic rollover. A later term requires a new roster, offering namespace, store and route plan; do not repoint these URLs at a new cohort.

## Runtime configuration

Keep existing OAuth credentials, session secret, Mirror database and delivery settings. Add:

```text
COURSE_WORKSPACE_ENABLED=true
COURSE_WORKSPACE_URL=https://jweath.com/entr/workspace
PROGRESS_ROSTER_PATH=/data/5500-roster.private.json
PROGRESS_DB_PATH=/data/progress-2026-fall.db
COURSE_DIRECTORY_SOURCES_PATH=/data/directory-sources.private.json
```

`PROGRESS_ROSTER_PATH` uses the validated group roster: workspace, explicit instructor Slack IDs, groups with stable IDs, section, members, team channel and source-backed initial milestones. The file is private runtime data, never a public asset or Git fixture. An invalid source closes 5500 access without revoking valid 5000 access.

The optional directory sources file follows `DirectorySources` in `directory.py`. `enrollment_snapshot` contains an offset-aware check time, source label, and students with section, Slack ID and source ID. It separates enrollment from group membership. Snapshot enrollment grants 5500 access; absent members do not inherit access through an old group sheet. Instructor access still comes from the explicit roster instructor list. Until an enrollment source is connected, the group roster provides a clearly bounded bootstrap view. Historical aggregate observations can be displayed as discrepancies; they never create members or change either source.

Refresh source files atomically after review. Enrollment snapshot access remains in force until the source file changes; this release does not automatically track adds/drops. Attendance eligibility start/end dates are not treated as course-access expiry dates. A roster correction is made in its source, then the reviewed snapshot is refreshed; the directory is not a second roster editor.

## Deployment and recovery

1. Back up the existing Mirror SQLite database through its backup API and preserve the existing delivery hold/disabled flags.
2. Place validated source files on the existing private `/data` volume with owner-only permissions. They contain records, not credentials. Do not upload them in a source archive or commit them.
3. Deploy this service with workspace configuration. Confirm health, anonymous rejection, scoped APIs, and an actual instructor Slack session.
4. Deploy the corresponding course-site proxy, navigation and public-brief changes. Verify the canonical URLs and section routes.
5. Verify the 19-project Mirror map and existing records are intact. The deployment must not activate class messaging or schedule catch-up prompts.

The existing daily volume backup includes the separate progress database and source files on `/data`. No new database service, worker, OAuth application or credential is required. Do not claim a backup restore test from snapshot availability alone.

For rollback, revert the course navigation/proxies and disable `COURSE_WORKSPACE_ENABLED`; retain the existing Mirror source and data. Shared cookies remain valid for 5000 while their server sessions and current roster grants remain valid. Preserve progress files for recovery. Do not delete or rewrite course records during rollback.

Local QA wrappers and private source snapshots belong in ignored `.local/`. The production app has no impersonation or unauthenticated preview mode.

## Preparation and reflection loop

5500 preparation is read from the existing entrepreneur-project Slack posts by
instOS Participation. Students do not submit a second dashboard form. The current
assignment is Dropbox/Cork’d for October 27. A–D discuss Dropbox; E–I discuss Cork’d
(including the instructor's October 23 clarification for morning Group I).
The instructor's planning cutoff is two hours before each section: 09:35 and 12:55
America/New_York. The assignment remains due before class. A cutoff is not an
attendance rule or a new graded deadline.

The participation service owns read provenance, observed message versions,
three-part extraction, and reflections linked to the existing participation
receipt. It reads only configured channels and exact enrolled Slack identities.
Numbered or labeled responses can be extracted; other substantial posts stay
reviewable. A read error retains the previous evidence and marks coverage
incomplete. Observed versions before a cutoff are retained separately from later
edits; text edited before the first read cannot be reconstructed. Topic counts
are deterministic word matches, and displayed questions are student quotations.
There is no model-provider call or automatic assessment of a misconception.

The workspace uses `COURSE_LEARNING_TOKEN` to GET the participation service's
`/learning/snapshot`. This independent credential permits learning reads only;
it is not an instructor credential and cannot read grades, correct attendance,
change reminders, or write learning records. The source URL defaults to the
existing participation API. Cache freshness/failure is visible. Every response
is filtered again through the current course directory before serving it.
Students receive their own prep and reflections only; instructors receive only
sections they teach. No learning data or photos enters the static course build.

The existing bot's participation form adds optional takeaway, muddiest point,
and next-question inputs when `COURSE_REFLECTIONS_ENABLED=true`. One transaction
saves the existing participation receipt and its reflection. Neither reflection
content nor preparation completion changes the 0–3 rating or attendance policy.
No additional reminder is scheduled. Attendance-only days retain their short form.

Slack avatars use exact member IDs, a six-hour source cache, known Slack/Gravatar
HTTPS hosts, and initials on missing/broken photos. Only the photo URL and check
time are retained from profile data. Names continue to come from the reviewed
course rosters. Project views remain behind shared Slack sign-in.

Deployment order: back up participation PostgreSQL; apply migration 010 through
the API's existing predeploy command; deploy participation API and worker from the
same service source; configure its reviewed private mappings and scoped bridge
secret; then deploy this workspace. Keep existing tenant, allowlist, reminder
flags and outbox intact. Mirror class messaging remains separately disabled.
Rollback can disable `COURSE_REFLECTIONS_ENABLED`, remove the learning config,
and deploy prior sources. Keep the additive learning tables and receipt evidence;
do not roll back or recreate the participation database to revert a UI.
