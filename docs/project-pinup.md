# Project pinup · first working slice

The instructor project board at `/pinup` puts each configured project's testable product, desired outcome, next useful test, commitment, repository evidence, and captured project updates together. It uses the existing course map, GitHub collector, scoped Slack capture, SQLite volume, and instructor authentication. No second service or database is needed.

## What the first version does

- Instructor-edited pins are source-linked. Each pin is labeled **student statement** or **instructor note**; an instructor note must not be presented as the student's own goal. Use one source or linked brief supporting the entire pin. Empty fields remain explicitly missing. Dates are entered only when stated.
- Product links open a live site, app invitation, or other testable build. The service does not fetch arbitrary product URLs or frame sites. A link is not a successful usability test.
- Repository activity is projected at project level, including contributions from accounts outside the student map. Separate per-student attribution remains unchanged. The board does not turn commit counts or issue status into effort, completion, or learning scores.
- Each partner's captured exit tickets retain their own author. Private notes, journals, and digests are excluded from the board projection. The board does not subscribe to all channel history or reinterpret ordinary conversation as a journal.
- Saving a pin requires the revision the editor opened. Concurrent edits return HTTP 409 instead of silently overwriting another review. Pins are scoped to the current sprint, retained under the course retention period, and do not carry forward automatically.
- Missing access and incomplete collections are visible. A recent failed attempt never appears as a complete collection. Evidence older than 48 hours and pin sources older than seven days are marked for review.

## Update contract

The visible page reads `/api/pinup` every 30 seconds, pausing while hidden or editing. Refresh reads saved records; it does not trigger a source crawl. The existing background collector still runs about every six hours when the course is active and `github_enabled` is true. The existing manual collection button is available for an immediate check. GitHub snapshots cover a rolling 14 days with up to 100 displayed project items; the card shows eight recent items and links to the repository/issues for more.

Slack uses the existing signed prompt-thread and command endpoints. Installing an app manifest without event subscriptions does not deliver ordinary prompt replies. Complete the existing activation/rehearsal before claiming live Slack capture. No sending, activation, broadened capture, or credentials are enabled by this feature.

## API and course site

- `GET /pinup`: public HTML shell, containing no student data.
- `GET /api/pinup`: instructor-authenticated project projection; `Cache-Control: no-store`.
- `PUT /api/pinup/projects/{id}`: instructor-authenticated `{pin, expected_revision}` update. Unknown project: 404; changed revision: 409; invalid/unattributed pin: 422. First save uses `expected_revision: null`.

The static course site can link to `/pinup` with an **instructor preview** label after this version is deployed. Do not put the instructor token, private roster, or JSON response into the static site. The first version intentionally has no student/class login and no public data feed.

## Path to the shared digital pinup

1. Reconcile the authoritative roster and project repository/build links. Renames and pivots need explicit review; shared channel membership does not identify project owners.
2. Connect the Mirror Slack app and a read-only GitHub credential where needed; rehearse one verified project. Capture ordinary existing updates only through an explicitly designed, bounded import or opt-in protocol.
3. Add student-maintained goals/commitments through a reviewed project source or authenticated owner editor, keeping individual reflections separate. No new journal requirement is introduced here.
4. Add cohort authentication and an explicitly shared field projection, then link that view from the course homepage. A public showcase needs a separate project-level publication choice and tests proving private sources and coaching cannot leak through summaries, URLs, or activity metadata.
5. Shorten collection latency through a configurable bounded polling interval or signed GitHub events, with reconciliation after missed events. Current six-hour collection is an initial integration, not instant source delivery.

This is a working instructor preview toward the shared dashboard, not a completed class-wide rollout. It changes no course requirements, deadlines, grading, peer assignments, or outgoing messages.
