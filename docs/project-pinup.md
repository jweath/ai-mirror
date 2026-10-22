# Course project pinup

The roster-restricted board lives at `https://jweath.com/entr/5000/2026/fall/`, proxied to Mirror’s `/course/` app. It combines 19 configured project rooms with source-backed shared pins, build links, owner updates, and GitHub evidence. The earlier bearer-protected `/pinup` remains an instructor workspace.

## Access and sharing

Slack OpenID Connect verifies identity; the course roster grants access on every request. Workspace membership alone is insufficient. Students can read shared project records. Instructors can edit pins and explicitly mark them shared. Private pins, muddy points, journals, digests, and coaching remain outside the student projection. The public course build contains neither student records nor credentials.

## Source collection

The browser checks saved records every 30 seconds while visible, retaining the editor and open source sections. GitHub collection runs hourly without a service token, or every 30 minutes with one. Slack history is checked every 10 minutes; signed events update records between polls. Read-only collection is independent of class messaging activation. The GitHub and Slack history windows are 14 days, with bounded records and visible access failures.

A configured GitHub Slack app can supply notification titles and source links already shared in the registered project rooms. These appear as `GitHub via Slack`; notification bodies are not retained. A Slack feed does not establish direct GitHub API access or a complete commit history. Missing repository links and inaccessible repositories remain explicit gaps. Do not infer effort, learning, ownership, or achievement from activity counts.

## Operation

Set the exact dashboard callback URL, Slack OAuth client credentials, bot token, signing secret, and a fresh session secret. Invite the bot to registered rooms and verify signed events. Import the real roster privately, leaving messaging inactive unless its separate schedule/rehearsal has been approved. Instructor edits retain revision checks and source attribution. See [activation](activation.md) and [operations](operations.md).

This rollout changes no assignments, deadlines, grading, peer assignments, or outgoing feedback.
